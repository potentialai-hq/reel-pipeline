#!/usr/bin/env python3
"""Блоки речи одного спикера из JSON шлюза myos-transcribe (segments со speaker).

Запуск: python3 блоки_речи.py <transcript_words.json> <SPEAKER_X> <Имя> <выход.md> [--имена A=Наталья,B=Станислав,C=Михаил]

Блок: подряд идущие реплики спикера. Короткая чужая реплика (до 12 с) внутри
не рвёт блок, а вписывается в квадратных скобках с именем, как в разметке для
отбора кандидатов на Рилсы. Формат заголовка:
«## Блок N · ЧЧ:ММ:СС–ЧЧ:ММ:СС · начало-конец · речь X с».
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ЧУЖАЯ_РЕПЛИКА_МАКС = 12.0  # секунд чужой речи, которая не рвёт блок
МИНИМУМ_РЕЧИ = 8.0         # блоки короче не нужны для отбора


def чч_мм_сс(секунды: float) -> str:
    с = int(секунды)
    return f"{с // 3600:02d}:{с % 3600 // 60:02d}:{с % 60:02d}"


def main() -> None:
    п = argparse.ArgumentParser()
    п.add_argument("json")
    п.add_argument("спикер")
    п.add_argument("имя")
    п.add_argument("выход")
    п.add_argument("--имена", default="SPEAKER_A=Наталья,SPEAKER_B=Станислав,SPEAKER_C=Михаил")
    а = п.parse_args()
    имена = dict(пара.split("=", 1) for пара in а.имена.split(",") if "=" in пара)
    сегменты = json.loads(Path(а.json).read_text(encoding="utf-8"))["segments"]

    блоки: list[dict] = []
    текущий: dict | None = None
    чужие: list[dict] = []
    for с in сегменты:
        свой = с.get("speaker") == а.спикер
        if свой:
            if текущий is None:
                текущий = {"начало": с["start"], "конец": с["end"], "части": [], "речь": 0.0}
                чужие = []
            elif чужие:
                длина_чужих = чужие[-1]["end"] - чужие[0]["start"]
                if длина_чужих > ЧУЖАЯ_РЕПЛИКА_МАКС:
                    блоки.append(текущий)
                    текущий = {"начало": с["start"], "конец": с["end"], "части": [], "речь": 0.0}
                else:
                    for ч in чужие:
                        текущий["части"].append(f"[{имена.get(ч.get('speaker'), ч.get('speaker'))}: {ч['text'].strip()}]")
                чужие = []
            текущий["части"].append(с["text"].strip())
            текущий["конец"] = с["end"]
            текущий["речь"] += с["end"] - с["start"]
        elif текущий is not None:
            чужие.append(с)
    if текущий is not None:
        блоки.append(текущий)

    блоки = [б for б in блоки if б["речь"] >= МИНИМУМ_РЕЧИ]
    строки = [f"# Блоки речи: {а.имя} ({а.спикер})", ""]
    for н, б in enumerate(блоки, 1):
        строки.append(
            f"## Блок {н} · {чч_мм_сс(б['начало'])}–{чч_мм_сс(б['конец'])} · "
            f"{б['начало']:.1f}-{б['конец']:.1f} · речь {б['речь']:.0f} с"
        )
        строки.append(" ".join(б["части"]))
        строки.append("")
    Path(а.выход).write_text("\n".join(строки), encoding="utf-8")
    print(f"блоков: {len(блоки)} · {а.выход}")


if __name__ == "__main__":
    main()
