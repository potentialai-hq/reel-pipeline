#!/usr/bin/env python3
"""Собирает пачку роликов: все Рилсы/*.md, у которых ещё нет cut/<ролик>.mp4.

Запуск: python3 собрать_пакет.py [--стиль "Фирменный стиль — подкаст.md"] [--корень .] [--только имя,имя]
Печатает итог по каждому ролику; сбой одного ролика не останавливает остальные.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    п = argparse.ArgumentParser()
    п.add_argument("--стиль", default="Фирменный стиль.md")
    п.add_argument("--корень", default=".")
    п.add_argument("--только", default="")
    a = п.parse_args()
    корень = Path(a.корень).resolve()
    только = {x for x in a.только.split(",") if x}
    итоги = []
    for md in sorted((корень / "Рилсы").glob("*.md")):
        имя = md.stem
        if только and имя not in только:
            continue
        if (корень / "cut" / f"{имя}.mp4").is_file():
            итоги.append((имя, "есть"))
            continue
        старт = time.time()
        лог = корень / "plan" / f"{имя}.log"
        лог.parent.mkdir(exist_ok=True)
        with лог.open("w", encoding="utf-8") as f:
            код = subprocess.run([sys.executable, str(Path(__file__).with_name("собрать_рилс.py")),
                                  str(md.relative_to(корень)), "--стиль", a.стиль],
                                 cwd=корень, stdout=f, stderr=subprocess.STDOUT).returncode
        итоги.append((имя, f"готово {time.time() - старт:.0f} с" if код == 0 else f"сбой, см. plan/{имя}.log"))
        print(f"{имя}: {итоги[-1][1]}", flush=True)
    сбои = [и for и in итоги if и[1].startswith("сбой")]
    print(f"итого: {len(итоги)} роликов, сбоев {len(сбои)}")
    return 1 if сбои else 0


if __name__ == "__main__":
    sys.exit(main())
