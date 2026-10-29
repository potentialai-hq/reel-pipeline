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
    return куски  # порядок монтажа сохраняется, окна считаются отдельно


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


ЗАЗОР_ОКОН = 20.0  # секунд между отрезками мастера, до которых они идут одним окном


def окна_кусков(куски: list[tuple[float, float]]) -> list[list[float]]:
    """Окна мастера с запасом по краям; далёкие отрезки режутся отдельными окнами."""
    окна: list[list[float]] = []
    for a, b in sorted(куски):
        a0, b0 = max(a - ЗАПАС, 0.0), b + ЗАПАС
        if окна and a0 - окна[-1][1] < ЗАЗОР_ОКОН:
            окна[-1][1] = max(окна[-1][1], b0)
        else:
            окна.append([a0, b0])
    return окна


def в_время_сырья(t: float, окна: list[list[float]]) -> float:
    """Переводит секунду мастера в секунду склеенного сырья."""
    сдвиг = 0.0
    for a0, b0 in окна:
        if a0 <= t <= b0:
            return round(t - a0 + сдвиг, 3)
        сдвиг += b0 - a0
    raise SystemExit(f"секунда мастера {t} вне окон {окна}")


def вырезать_окна(мастер: Path, выход: Path, окна: list[list[float]]) -> None:
    if len(окна) == 1:
        вырезать_окно(мастер, выход, окна[0][0], окна[0][1])
        return
    части = []
    for н, (a0, b0) in enumerate(окна):
        часть = выход.with_name(f"{выход.stem}_окно{н}.mp4")
        вырезать_окно(мастер, часть, a0, b0)
        части.append(часть)
    список = выход.with_name(f"{выход.stem}_окна.txt")
    список.write_text("".join(f"file '{ч.name}'\n" for ч in части), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(список),
                    "-c", "copy", "-movflags", "+faststart", str(выход)], check=True)
    for ч in части:
        ч.unlink()
    список.unlink()


def слова_окна(слова_шлюза: Path, окна: list[list[float]]) -> dict:
    данные = json.loads(слова_шлюза.read_text(encoding="utf-8"))
    слова = []
    длина = sum(b0 - a0 for a0, b0 in окна)
    for a0, b0 in окна:
        for сегмент in данные["segments"]:
            for w in сегмент.get("words") or []:
                s, e = float(w["start"]), float(w["end"])
                if e < a0 or s > b0:
                    continue
                слова.append({"word": str(w["word"]).strip(),
                              "start": в_время_сырья(max(s, a0), окна),
                              "end": в_время_сырья(min(e, b0), окна)})
    return {"segments": [{"start": 0.0, "end": round(длина, 3), "words": слова}]}


def описание(ролик: str, исходник: str, куски: list[tuple[float, float]], окна: list[list[float]],
             обложка1: str, обложка2: str, заголовок: str) -> str:
    строки = ["---", f"ролик: {ролик}", f"исходник: {исходник}", "куски:"]
    for a, b in куски:
        строки.append(f"  - [{в_время_сырья(a, окна):.2f}, {в_время_сырья(b, окна):.2f}]")
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
    окна = окна_кусков(куски)
    исходник = f"{a.ролик}.mp4"

    вырезать_окна(Path(a.мастер), корень / "raw" / исходник, окна)
    (корень / "transcripts").mkdir(exist_ok=True)
    (корень / "transcripts" / f"{a.ролик}.json").write_text(
        json.dumps(слова_окна(Path(a.слова), окна), ensure_ascii=False, indent=1), encoding="utf-8")
    (корень / "Рилсы").mkdir(exist_ok=True)
    md = корень / "Рилсы" / f"{a.ролик}.md"
    md.write_text(описание(a.ролик, исходник, куски, окна, a.обложка1, a.обложка2, a.заголовок), encoding="utf-8")
    print(f"окна {', '.join(f'{a0:.1f}-{b0:.1f}' for a0, b0 in окна)} · raw/{исходник} · transcripts/{a.ролик}.json · {md.relative_to(корень)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
