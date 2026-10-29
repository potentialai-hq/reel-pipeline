#!/usr/bin/env python3
"""Из файла «Кандидаты на Рилсы» делает сырьё и описания роликов через подкаст_в_рилс.py.

Читает блоки «## N. Название» с полями «Файл», «Отрезки», «Обложка». Пропускает ролики,
у которых уже есть cut/<файл>.mp4 (собраны) или raw/<файл>.mp4 (сырьё готово).
Запуск: python3 кандидаты_в_описания.py <кандидаты.md> --мастер <mp4> --слова <json> [--корень .] [--только имя,имя]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def разобрать(текст: str) -> list[dict]:
    кандидаты = []
    for блок in re.split(r"^## (?=\d+\. )", текст, flags=re.M)[1:]:
        заголовок = блок.splitlines()[0]
        номер, название = заголовок.split(". ", 1)
        файл = re.search(r"\*\*Файл:\*\*\s*(\S+)", блок)
        отрезки = re.search(r"\*\*Отрезки:\*\*\s*(.+)", блок)
        обложка = re.search(r"\*\*Обложка:\*\*\s*«(.*?)»\s*/\s*«(.*?)»", блок)
        if not (файл and отрезки and обложка):
            print(f"кандидат {номер}: нет Файл/Отрезки/Обложка, пропуск", file=sys.stderr)
            continue
        пары = re.findall(r"\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]", отрезки.group(1))
        кандидаты.append({
            "номер": int(номер), "название": название.strip().strip("«»"), "файл": файл.group(1),
            "куски": ",".join(f"{a}-{b}" for a, b in пары),
            "обложка1": обложка.group(1), "обложка2": обложка.group(2),
        })
    return кандидаты


def main() -> int:
    п = argparse.ArgumentParser()
    п.add_argument("кандидаты")
    п.add_argument("--мастер", required=True)
    п.add_argument("--слова", required=True)
    п.add_argument("--корень", default=".")
    п.add_argument("--только", default="")
    a = п.parse_args()
    корень = Path(a.корень).resolve()
    только = {x for x in a.только.split(",") if x}
    for к in разобрать(Path(a.кандидаты).read_text(encoding="utf-8")):
        if только and к["файл"] not in только:
            continue
        if (корень / "cut" / f"{к['файл']}.mp4").is_file() or (корень / "raw" / f"{к['файл']}.mp4").is_file():
            print(f"= {к['файл']}: уже есть, пропуск")
            continue
        print(f"→ {к['файл']}: {к['куски']}")
        subprocess.run([sys.executable, str(Path(__file__).with_name("подкаст_в_рилс.py")),
                        "--мастер", a.мастер, "--слова", a.слова, "--ролик", к["файл"], "--куски", к["куски"],
                        "--обложка1", к["обложка1"], "--обложка2", к["обложка2"], "--заголовок", к["название"],
                        "--корень", str(корень)], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
