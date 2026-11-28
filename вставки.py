#!/usr/bin/env python3
"""Вставки в исходник рилса: перебивки другим видео и крупные титры.

Читает раздел ``вставки`` из YAML-шапки описания ролика и собирает новую
SDR-копию исходника, в которой на заданных отрезках поверх картинки лежит
перебивка и (или) титр. Звук исходника не меняется, поэтому речь идёт
дальше под перебивкой, а монтаж и субтитры сборщик кладёт уже поверх.

Время вставок задаётся по исходнику (те же секунды, что в ``куски``).
Чистая копия хранится рядом как ``raw_sdr/<имя>.чистый.mov``: повторный
запуск всегда собирает от неё, результат не накапливается.

    вставки:
      - с: 78.2            # начало в исходнике, секунды
        до: 81.6           # конец в исходнике
        видео: IMG_0415.mov  # файл из raw_sdr/, необязательно
        от: 9.0            # с какой секунды брать перебивку
        скорость: 0.8      # 1.0 обычная, меньше значит медленнее
        текст: ["Боль длится", "недолго"]   # необязательно; вторая строка акцентная
        позиция: 0.36      # верх титра, доля высоты

Запуск: ``python3 вставки.py Рилсы/<ролик>.md`` и затем обычная сборка.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

КОРЕНЬ = Path(__file__).resolve().parent
ШРИФТЫ = КОРЕНЬ / "assets" / "fonts"
W, H = 1080, 1920
ЗАТУХАНИЕ = 0.25
ЦВЕТ_ОСНОВНОЙ = (245, 240, 225, 255)
ЦВЕТ_АКЦЕНТА = (255, 210, 63, 255)


def _шапка(путь: Path) -> dict:
    текст = путь.read_text(encoding="utf-8")
    if not текст.startswith("---"):
        raise SystemExit(f"В файле {путь} нет YAML-шапки")
    return yaml.safe_load(текст.split("---", 2)[1]) or {}


def _шрифт(имя: str, размер: int, строка: str, ширина: int) -> ImageFont.FreeTypeFont:
    шрифт = ImageFont.truetype(str(ШРИФТЫ / имя), размер)
    перо = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    while перо.textlength(строка, font=шрифт) > ширина and размер > 40:
        размер -= 4
        шрифт = ImageFont.truetype(str(ШРИФТЫ / имя), размер)
    return шрифт


def _строка(холст: Image.Image, строка: str, шрифт, y: int, цвет) -> None:
    перо = ImageDraw.Draw(холст)
    x = (W - перо.textlength(строка, font=шрифт)) / 2
    тень = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(тень).text((x + 4, y + 7), строка, font=шрифт, fill=(0, 0, 0, 215))
    холст.alpha_composite(тень.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(холст).text((x, y), строка, font=шрифт, fill=цвет)


def нарисовать_титр(строки: list[str], позиция: float, путь: Path, вуаль: bool) -> None:
    """Первая строка рубленая, остальные курсивные акцентные, как на обложке.

    Поверх перебивки кадр слегка затемняется; поверх лица под текст кладётся
    тёмная плашка, иначе жёлтый курсив теряется на светлом фоне.
    """
    холст = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    перо = ImageDraw.Draw(холст)
    набор = []
    y = int(H * позиция)
    for номер, строка in enumerate(строки):
        if номер == 0:
            шрифт = _шрифт("Unbounded.ttf", 92, строка, W - 160)
            try:
                шрифт.set_variation_by_axes([800])
            except Exception:
                pass
            набор.append((строка, шрифт, y, ЦВЕТ_ОСНОВНОЙ)); y += int(шрифт.size * 1.25)
        else:
            шрифт = _шрифт("CormorantGaramondItalic.ttf", 176, строка, W - 160)
            набор.append((строка, шрифт, y, ЦВЕТ_АКЦЕНТА)); y += int(шрифт.size * 0.95)
    if вуаль:
        холст.alpha_composite(Image.new("RGBA", (W, H), (8, 18, 28, 70)))
    else:
        ширина = max(перо.textlength(строка, font=шрифт) for строка, шрифт, _, _ in набор)
        верх, низ = набор[0][2] - 36, y + 44
        плашка = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(плашка).rounded_rectangle(
            [(W - ширина) / 2 - 56, верх, (W + ширина) / 2 + 56, низ], radius=44, fill=(10, 20, 30, 165))
        холст.alpha_composite(плашка)
    for строка, шрифт, y0, цвет in набор:
        _строка(холст, строка, шрифт, y0, цвет)
    холст.save(путь)


def собрать(описание: Path, корень: Path) -> Path:
    шапка = _шапка(описание)
    вставки = шапка.get("вставки") or []
    имя = Path(шапка["исходник"]).with_suffix(".mov").name
    готовый = корень / "raw_sdr" / имя
    чистый = готовый.with_suffix(".чистый.mov")
    if not чистый.is_file():
        if not готовый.is_file():
            raise SystemExit(f"Нет SDR-копии {готовый}: сначала python3 тонмап.py")
        shutil.copy2(готовый, чистый)
    if not вставки:
        shutil.copy2(чистый, готовый)
        print(f"Вставок нет, возвращена чистая копия: {готовый}")
        return готовый

    частота = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "stream=r_frame_rate", "-of", "csv=p=0", str(чистый)],
        capture_output=True, text=True, check=True).stdout.split()[0].strip(",")

    with tempfile.TemporaryDirectory(prefix="vstavki_") as врем:
        входы: list[str] = ["-i", str(чистый)]
        цепочка: list[str] = []
        слой, номер_входа = "[0:v]", 1
        for номер, вставка in enumerate(вставки, 1):
            с, до = float(вставка["с"]), float(вставка["до"])
            if до <= с:
                raise SystemExit(f"Вставка {номер}: «до» должно быть больше «с»")
            длина = до - с
            рамка = (f"fade=t=in:st={с:.3f}:d={ЗАТУХАНИЕ}:alpha=1,"
                     f"fade=t=out:st={до - ЗАТУХАНИЕ:.3f}:d={ЗАТУХАНИЕ}:alpha=1")
            окно = f"enable='between(t,{с:.3f},{до:.3f})':eof_action=pass"
            if вставка.get("видео"):
                скорость = float(вставка.get("скорость", 1.0))
                от = float(вставка.get("от", 0.0))
                входы += ["-i", str(корень / "raw_sdr" / вставка["видео"])]
                # замедление: недостающие кадры смешиваются из соседних, иначе вода и шаги дёргаются
                плавность = (f"framerate=fps={частота}:interp_start=0:interp_end=255:scene=100"
                             if скорость < 1 else f"fps={частота}")
                цепочка.append(
                    f"[{номер_входа}:v]trim=start={от:.3f}:duration={длина * скорость:.3f},"
                    f"setpts=(PTS-STARTPTS)/{скорость}+{с:.3f}/TB,{плавность},"
                    f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                    f"format=yuva420p,{рамка}[b{номер}]")
                цепочка.append(f"{слой}[b{номер}]overlay={окно}[v{номер}b]")
                слой, номер_входа = f"[v{номер}b]", номер_входа + 1
            if вставка.get("текст"):
                картинка = Path(врем) / f"titr_{номер}.png"
                нарисовать_титр(list(вставка["текст"]), float(вставка.get("позиция", 0.36)),
                                картинка, вуаль=bool(вставка.get("видео")))
                входы += ["-loop", "1", "-framerate", частота, "-t", f"{длина:.3f}", "-i", str(картинка)]
                цепочка.append(
                    f"[{номер_входа}:v]setpts=PTS-STARTPTS+{с:.3f}/TB,format=yuva420p,{рамка}[t{номер}]")
                цепочка.append(f"{слой}[t{номер}]overlay={окно}[v{номер}t]")
                слой, номер_входа = f"[v{номер}t]", номер_входа + 1
        цепочка.append(f"{слой}format=yuv420p[out]")
        выход = Path(врем) / "out.mov"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *входы, "-filter_complex", ";".join(цепочка),
             "-map", "[out]", "-map", "0:a", "-c:a", "copy",
             "-c:v", "h264_videotoolbox", "-b:v", "22M", "-profile:v", "high",
             "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
             str(выход)], check=True)
        shutil.move(str(выход), str(готовый))
    print(f"Вставок: {len(вставки)}. Готово: {готовый}")
    return готовый


def main(аргументы: list[str] | None = None) -> int:
    парсер = argparse.ArgumentParser(description="Перебивки и титры в исходнике рилса.")
    парсер.add_argument("ролик", help="Markdown-файл с описанием ролика")
    парсер.add_argument("--корень", default=".", help="Папка с raw_sdr/")
    args = парсер.parse_args(аргументы)
    собрать(Path(args.ролик), Path(args.корень).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
