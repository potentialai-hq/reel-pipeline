#!/usr/bin/env python3
"""Сырьё ролика с камеры участника вместо студийного мастера.

Мастер это монтаж; камера пишет непрерывно. Для каждого окна ролика (те же окна,
что у подкаст_в_рилс.py, поэтому описание и правки субтитров переиспользуются)
смещение камеры относительно мастера ищется по звуку: сначала грубо по общему
миксу в широком диапазоне, потом точно по самой камере. Источники читаются по
HTTP (rclone serve http), на диск попадает только вырезанное окно.

Запуск:
  python3 камера_в_рилс.py --описание Рилсы/<ролик>.md --мастер <url> --микс <url> --камера <url> \
      --слова <json шлюза> [--суффикс -cam] [--смещения .meta/смещения.json] [--корень .]
Описание берётся готовое (с правками субтитров) и копируется под новым именем.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from подкаст_в_рилс import ЗАПАС, окна_кусков, слова_окна, вырезать_окно

ЧАСТОТА = 8000
ОБРАЗЕЦ = 15.0       # секунд звука мастера для сверки
ДИАПАЗОН_МИКС = 600.0  # на сколько секунд вперёд искать в миксе (монтаж только вырезает)
ДИАПАЗОН_КАМЕРА = 6.0  # уточнение по камере вокруг найденного в миксе


def звук(url: str, начало: float, длина: float) -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
        путь = f.name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(начало, 0):.3f}", "-t", f"{длина:.3f}",
                    "-i", url, "-vn", "-ac", "1", "-ar", str(ЧАСТОТА), "-f", "s16le", путь], check=True)
    a = np.fromfile(путь, dtype=np.int16).astype(np.float32)
    Path(путь).unlink(missing_ok=True)
    return a - a.mean()


def сдвиг(образец: np.ndarray, поле: np.ndarray) -> tuple[float, float]:
    """Смещение образца внутри поля в секундах и нормированная корреляция."""
    n = len(образец) + len(поле)
    c = np.fft.irfft(np.fft.rfft(поле, n) * np.conj(np.fft.rfft(образец, n)), n)[: len(поле)]
    i = int(np.argmax(c))
    q = c[i] / (np.linalg.norm(образец) * np.linalg.norm(поле[i:i + len(образец)]) + 1e-9)
    return i / ЧАСТОТА, float(q)


def смещение_окна(мастер: str, микс: str, камера: str, t: float, догадка: float) -> dict:
    образец = звук(мастер, t, ОБРАЗЕЦ)
    начало_поиска = max(t + догадка - 5.0, 0.0)
    поле = звук(микс, начало_поиска, ДИАПАЗОН_МИКС + ОБРАЗЕЦ + 5.0)
    l, q1 = сдвиг(образец, поле)
    смещение_микса = начало_поиска + l - t
    начало_кам = max(t + смещение_микса - ДИАПАЗОН_КАМЕРА, 0.0)
    поле_кам = звук(камера, начало_кам, 2 * ДИАПАЗОН_КАМЕРА + ОБРАЗЕЦ)
    l2, q2 = сдвиг(образец, поле_кам)
    смещение_камеры = начало_кам + l2 - t
    return {"мастер": round(t, 3), "смещение_микс": round(смещение_микса, 3), "корр_микс": round(q1, 3),
            "смещение_камера": round(смещение_камеры, 3), "корр_камера": round(q2, 3)}


def main() -> int:
    п = argparse.ArgumentParser()
    п.add_argument("--описание", required=True)
    п.add_argument("--мастер", required=True)
    п.add_argument("--микс", required=True)
    п.add_argument("--камера", required=True)
    п.add_argument("--слова", required=True)
    п.add_argument("--суффикс", default="-cam")
    п.add_argument("--смещения", default="")
    п.add_argument("--корень", default=".")
    п.add_argument("--зазор", type=float, default=None,
                   help="зазор между окнами; задать тот же, что был у описания (старые описания резались одним окном: 999)")
    a = п.parse_args()
    корень = Path(a.корень).resolve()
    md = Path(a.описание)
    текст = md.read_text(encoding="utf-8")
    отрезки = re.search(r"Отрезки в мастере:\s*(.+?)\.\s*$", текст, flags=re.M)
    if not отрезки:
        raise SystemExit("в описании нет строки «Отрезки в мастере: a-b, c-d.»")
    куски = [tuple(map(float, ч.strip().split("-"))) for ч in отрезки.group(1).split(",")]
    окна = окна_кусков(куски, a.зазор) if a.зазор is not None else окна_кусков(куски)
    имя = md.stem + a.суффикс

    кэш = {}
    if a.смещения and Path(a.смещения).is_file():
        кэш = json.loads(Path(a.смещения).read_text(encoding="utf-8"))
    догадка = 3.5
    for ключ in sorted(кэш, key=float):
        if float(ключ) <= окна[0][0]:
            догадка = кэш[ключ]["смещение_камера"]
    части = []
    for н, (a0, b0) in enumerate(окна):
        ключ = f"{a0:.3f}"
        if ключ not in кэш:
            кэш[ключ] = смещение_окна(a.мастер, a.микс, a.камера, a0 + ЗАПАС, догадка)
            print(f"окно {a0:.1f}-{b0:.1f}: смещение камеры {кэш[ключ]['смещение_камера']:+.3f} с "
                  f"(корр микс {кэш[ключ]['корр_микс']:.2f}, камера {кэш[ключ]['корр_камера']:.2f})")
        догадка = кэш[ключ]["смещение_камера"]
        if кэш[ключ]["корр_камера"] < 0.5:
            raise SystemExit(f"окно {a0:.1f}: слабая корреляция с камерой {кэш[ключ]['корр_камера']:.2f}, не режу")
        часть = корень / "raw" / f"{имя}_окно{н}.mp4"
        вырезать_окно(a.камера, часть, a0 + догадка, b0 + догадка)
        части.append(часть)
    if a.смещения:
        Path(a.смещения).write_text(json.dumps(кэш, ensure_ascii=False, indent=1), encoding="utf-8")

    выход = корень / "raw" / f"{имя}.mp4"
    if len(части) == 1:
        части[0].replace(выход)
    else:
        список = выход.with_name(f"{имя}_окна.txt")
        список.write_text("".join(f"file '{ч.name}'\n" for ч in части), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(список),
                        "-c", "copy", "-movflags", "+faststart", str(выход)], check=True)
        for ч in части:
            ч.unlink()
        список.unlink()

    (корень / "transcripts").mkdir(exist_ok=True)
    (корень / "transcripts" / f"{имя}.json").write_text(
        json.dumps(слова_окна(Path(a.слова), окна), ensure_ascii=False, indent=1), encoding="utf-8")
    новое = re.sub(r"^ролик: .*$", f"ролик: {имя}", текст, count=1, flags=re.M)
    новое = re.sub(r"^исходник: .*$", f"исходник: {имя}.mp4", новое, count=1, flags=re.M)
    (корень / "Рилсы" / f"{имя}.md").write_text(новое, encoding="utf-8")
    print(f"готово: raw/{имя}.mp4 · transcripts/{имя}.json · Рилсы/{имя}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
