#!/usr/bin/env python3
"""Готовит ролик из длинного подкаста по пословному транскрипту шлюза myos-transcribe.

Вход: мастер-видео, JSON шлюза (segments[].words[] с word/start/end) и отрезки в секундах
от начала мастера. Выход в соглашениях конвейера: raw/<ролик>.mp4 (окно вокруг отрезков,
точная резка с перекодированием), transcripts/<ролик>.json (слова в формате Whisper,
сдвинутые к началу окна) и Рилсы/<ролик>.md (описание для собрать_рилс.py).

Пример:
  python3 подкаст_в_рилс.py --мастер podcast.mp4 --слова words.json --ролик storybox-01 \
      --куски 1234.5-1278.9 --обложка1 "Строка один" --обложка2 "строка два"
Дальше: python3 собрать_рилс.py Рилсы/storybox-01.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ЗАПАС = 1.0  # секунд окна до первого и после последнего отрезка


def разобрать_куски(текст: str) -> list[tuple[float, float]]:
    куски = []
    for часть in текст.split(","):
        a, b = часть.strip().split("-")
        a, b = float(a), float(b)
        if b <= a:
            raise SystemExit(f"кусок {часть}: конец должен быть больше начала")
        куски.append((a, b))
    return sorted(куски)


def вырезать_окно(мастер: Path, выход: Path, начало: float, конец: float) -> None:
    выход.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{начало:.3f}", "-i", str(мастер),
         "-t", f"{конец - начало:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-colorspace", "bt709", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         str(выход)],
        check=True,
    )


def слова_окна(слова_шлюза: Path, начало: float, конец: float) -> dict:
    данные = json.loads(слова_шлюза.read_text(encoding="utf-8"))
    слова = []
    for сегмент in данные["segments"]:
        for w in сегмент.get("words") or []:
            s, e = float(w["start"]), float(w["end"])
            if e < начало or s > конец:
                continue
            слова.append({"word": str(w["word"]).strip(),
                          "start": round(max(s - начало, 0.0), 3),
                          "end": round(min(e, конец) - начало, 3)})
    return {"segments": [{"start": 0.0, "end": round(конец - начало, 3), "words": слова}]}


def описание(ролик: str, исходник: str, куски: list[tuple[float, float]], начало: float,
             обложка1: str, обложка2: str, заголовок: str) -> str:
    строки = ["---", f"ролик: {ролик}", f"исходник: {исходник}", "куски:"]
    for a, b in куски:
        строки.append(f"  - [{a - начало:.2f}, {b - начало:.2f}]")
    строки += ["без_субтитров: []", "правки:", "  всегда: {}", "  по_времени: []",
               "финал:", '  исходник: ""', "  куски: []", "обложка:",
               f'  строка1: "{обложка1}"', f'  строка2: "{обложка2}"', '  стикер: ""',
               "---", "", f"# {заголовок or ролик}", "",
               f"Отрезки в мастере: " + ", ".join(f"{a:.1f}-{b:.1f}" for a, b in куски) + ".", ""]
    return "\n".join(строки)


def main(аргументы=None) -> int:
    п = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    п.add_argument("--мастер", required=True)
    п.add_argument("--слова", required=True, help="JSON шлюза myos-transcribe (--format json)")
    п.add_argument("--ролик", required=True, help="имя ролика латиницей или кириллицей без пробелов")
    п.add_argument("--куски", required=True, help="отрезки в секундах мастера: 1234.5-1278.9,1300-1320")
    п.add_argument("--обложка1", default="")
    п.add_argument("--обложка2", default="")
    п.add_argument("--заголовок", default="")
    п.add_argument("--корень", default=".")
    a = п.parse_args(аргументы)

    корень = Path(a.корень).resolve()
    куски = разобрать_куски(a.куски)
    начало = max(куски[0][0] - ЗАПАС, 0.0)
    конец = куски[-1][1] + ЗАПАС
    исходник = f"{a.ролик}.mp4"

    вырезать_окно(Path(a.мастер), корень / "raw" / исходник, начало, конец)
    (корень / "transcripts").mkdir(exist_ok=True)
    (корень / "transcripts" / f"{a.ролик}.json").write_text(
        json.dumps(слова_окна(Path(a.слова), начало, конец), ensure_ascii=False, indent=1), encoding="utf-8")
    (корень / "Рилсы").mkdir(exist_ok=True)
    md = корень / "Рилсы" / f"{a.ролик}.md"
    md.write_text(описание(a.ролик, исходник, куски, начало, a.обложка1, a.обложка2, a.заголовок), encoding="utf-8")
    print(f"окно {начало:.1f}-{конец:.1f} с · raw/{исходник} · transcripts/{a.ролик}.json · {md.relative_to(корень)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
