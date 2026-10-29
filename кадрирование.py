#!/usr/bin/env python3
"""Кадрирование 9:16 по лицу: смена планов и центр лица для каждого плана.

Студийный мастер подкаста смонтирован с переключением камер, и центр кадра
у каждой камеры свой. Обрезка по центру оставляет собеседника сбоку. Здесь
для куска [start, end] находятся границы планов (детектор сцен ffmpeg) и в
каждом плане центр самого крупного лица (OpenCV YuNet, модель в assets/models).
Результат: выражение x для фильтра crop, которое переключается по времени.

Проверка глазами: python3 кадрирование.py raw/<исходник>.mp4 [start] [end]
"""
from __future__ import annotations

import re
import statistics
import subprocess
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent
МОДЕЛЬ = КОРЕНЬ / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
ПОРОГ_СЦЕНЫ = 0.35
ШИРИНА_АНАЛИЗА = 640
МИНИМУМ_ПЛАНА = 0.4  # планы короче сливаются с соседним: там нечего ловить
ПОВОРОТ_ГОЛОВЫ = 0.12  # нос дальше этой доли полуширины лица от середины глаз: взгляд в сторону
ВОЗДУХ = 0.10  # на сколько долей ширины кадра лицо сдвигается от центра против взгляда


def планы(src: str | Path, start: float, end: float, порог: float = ПОРОГ_СЦЕНЫ) -> list[float]:
    """Границы планов в секундах от start (без 0 и конца)."""
    результат = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-to", str(end), "-i", str(src),
         "-vf", f"select='gt(scene,{порог})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    времена = [float(м) for м in re.findall(r"pts_time:([0-9.]+)", результат.stderr)]
    длина = end - start
    чистые: list[float] = []
    for t in sorted(времена):
        if t < МИНИМУМ_ПЛАНА or длина - t < МИНИМУМ_ПЛАНА:
            continue
        if чистые and t - чистые[-1] < МИНИМУМ_ПЛАНА:
            continue
        чистые.append(round(t, 3))
    return чистые


def _кадр(src: str | Path, момент: float):
    import cv2
    import numpy as np

    результат = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{момент:.3f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={ШИРИНА_АНАЛИЗА}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True,
    )
    if результат.returncode != 0 or not результат.stdout:
        return None
    return cv2.imdecode(np.frombuffer(результат.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)


_детектор = None


def _получить_детектор():
    global _детектор
    if _детектор is None:
        import cv2

        if not МОДЕЛЬ.is_file():
            raise FileNotFoundError(f"Нет модели лиц {МОДЕЛЬ}")
        _детектор = cv2.FaceDetectorYN.create(str(МОДЕЛЬ), "", (320, 320), 0.6)
    return _детектор


def центр_лица(src: str | Path, момент: float) -> tuple[float, int] | None:
    """(доля ширины кадра с центром самого крупного лица, взгляд) или None.

    Взгляд: -1 человек смотрит влево по кадру, +1 вправо, 0 в камеру. Считается
    по сдвигу носа от середины глаз (точки YuNet), поворот головы и есть взгляд
    в студийной съёмке.
    """
    кадр = _кадр(src, момент)
    if кадр is None:
        return None
    детектор = _получить_детектор()
    h, w = кадр.shape[:2]
    детектор.setInputSize((w, h))
    _, лица = детектор.detect(кадр)
    if лица is None or len(лица) == 0:
        return None
    x, _y, ww, _hh, г1x, _г1y, г2x, _г2y, носx, *_ = max(лица.tolist(), key=lambda л: л[2] * л[3])
    сдвиг = (носx - (г1x + г2x) / 2) / max(ww / 2, 1e-6)
    взгляд = -1 if сдвиг < -ПОВОРОТ_ГОЛОВЫ else 1 if сдвиг > ПОВОРОТ_ГОЛОВЫ else 0
    return round((x + ww / 2) / w, 4), взгляд


def центры_планов(src: str | Path, start: float, end: float) -> list[tuple[float, float, float | None, int]]:
    """Список (t0, t1, центр лица, взгляд) в секундах от start; центр None без лица."""
    границы = [0.0, *планы(src, start, end), end - start]
    результат = []
    for t0, t1 in zip(границы, границы[1:]):
        длина = t1 - t0
        доли = (0.5,) if длина < 1.5 else (0.25, 0.5, 0.75)
        найдено = [л for л in (центр_лица(src, start + t0 + длина * д) for д in доли) if л is not None]
        if найдено:
            центр = round(statistics.median(л[0] for л in найдено), 4)
            взгляд = round(statistics.median(л[1] for л in найдено))
            результат.append((t0, t1, центр, int(взгляд)))
        else:
            результат.append((t0, t1, None, 0))
    return результат


def положение_в_кадре(взгляд: int) -> float:
    """Доля ширины кадра, где стоит лицо: против взгляда остаётся воздух."""
    return round(0.5 - ВОЗДУХ * взгляд, 4)


def выражение_x(src: str | Path, start: float, end: float) -> str | None:
    """Выражение x для crop: лицо по планам с воздухом по взгляду; None, если лиц нет."""
    планы_ = центры_планов(src, start, end)
    if all(c is None for _t0, _t1, c, _в in планы_):
        return None
    куски = []
    последний = (0.5, 0)
    for _t0, _t1, c, в in планы_:
        последний = (c, в) if c is not None else последний
        куски.append(f"{последний[0]}*in_w-{положение_в_кадре(последний[1])}*out_w")
    выражение = куски[-1]
    for (t0, t1, _c, _в), кусок in reversed(list(zip(планы_[:-1], куски[:-1]))):
        выражение = f"if(lt(t,{t1}),{кусок},{выражение})"
    return f"clip({выражение},0,in_w-out_w)"


def main() -> None:
    src = sys.argv[1]
    start = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    if len(sys.argv) > 3:
        end = float(sys.argv[3])
    else:
        end = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
            capture_output=True, text=True).stdout.strip())
    for t0, t1, c, в in центры_планов(src, start, end):
        взгляд = {-1: "влево", 0: "в камеру", 1: "вправо"}[в]
        print(f"{t0:8.2f} - {t1:8.2f}  лицо x = {'нет' if c is None else c}  взгляд {взгляд}  лицо в кадре на {положение_в_кадре(в)}")


if __name__ == "__main__":
    main()
