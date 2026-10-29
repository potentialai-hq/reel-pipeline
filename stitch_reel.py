#!/usr/bin/env python3
"""Сборка рилса из кусков исходника по плану + субтитры из фирменного стиля.

Архитектура: PNG-состояния субтитров (слово подсвечено) → прозрачная
видеодорожка (concat demuxer + png-кодек в mov) → один overlay на видео.

План (JSON):
{
  "src": "raw/A001.mov",
  "out": "cut/04_harness.mp4",
  "pieces": [
    {"start": 1024.92, "end": 1088.80,
     "words": [{"text": "Что", "start": 1024.92, "end": 1025.40}, ...]}
  ]
}
Таймкоды слов — абсолютные (по исходнику). Текст слов — уже исправленный
(ошибки whisper правим в плане, тайминги остаются).

Использование: python3 stitch_reel.py plan/04_harness.json [Фирменный стиль.md]
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image

from cut_reel import group_phrases, отрисовщик_субтитров
import кадрирование
from стиль import кадров_в_секунду, загрузить_стиль, параметры_субтитров

# Цвет 23_06: исходники уже сконвертированы в SDR через Apple avconvert (нативный HLG->709
# тонмап, как айфон/QuickTime) -> raw/23_06_sdr/. Доп. грейд не нужен — passthrough.
GRADE = "null"


def run(cmd):
    subprocess.run(cmd, check=True)


def build_subs_track(words, duration, idx, tmp, стиль):
    """Прозрачный subs.mov: состояния «активное слово» с точными длительностями."""
    render, параметры = отрисовщик_субтитров(стиль)
    phrases = group_phrases(words, параметры)
    states = []  # (png, start, end) внутри куска
    for pi, phrase in enumerate(phrases):
        for wi, w in enumerate(phrase):
            png = tmp / f"pc{idx}_p{pi:02d}_w{wi:02d}.png"
            render(phrase, wi, png, параметры)
            until = phrase[wi + 1]["start"] if wi + 1 < len(phrase) else min(phrase[-1]["end"] + 0.15, duration)
            states.append((png, w["start"], until))

    blank = tmp / "blank.png"
    Image.new("RGBA", (параметры["ширина"], параметры["высота"]), (0, 0, 0, 0)).save(blank)

    lines, cursor = [], 0.0
    for png, s, e in states:
        if s > cursor + 0.01:
            lines.append((blank, s - cursor))
        lines.append((png, max(e - s, 0.04)))
        cursor = e
    if cursor < duration:
        lines.append((blank, duration - cursor))

    lst = tmp / f"subs_{idx}.txt"
    txt = ""
    for png, d in lines:
        # concat-протокол ffmpeg использует \ как escape-символ, поэтому пути
        # пишем через прямой слэш (as_posix) — так они работают и на Windows,
        # где resolve() иначе даёт C:\... с обратными слэшами.
        txt += f"file '{png.resolve().as_posix()}'\nduration {d:.3f}\n"
    txt += f"file '{lines[-1][0].resolve().as_posix()}'\n"
    lst.write_text(txt, encoding="utf-8")

    subs = tmp / f"subs_{idx}.mov"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:v", "png", "-vsync", "vfr", str(subs)])
    return subs


def фильтр_тела(duration, idx, стиль, смещение_x=None):
    """Собирает видеочасть фильтра куска с частотой из фирменного стиля.

    ``смещение_x`` это выражение crop из кадрирование.выражение_x: обрезка
    9:16 следует за лицом по планам, а не держится центра кадра.
    """
    fps = кадров_в_секунду(стиль)
    параметры = параметры_субтитров(стиль)
    ширина, высота = параметры["ширина"], параметры["высота"]
    zoom = стиль["монтаж"]["зум"]
    обрезка = (f"crop={ширина}:{высота}:x='{смещение_x}':y='(in_h-out_h)/2'"
               if смещение_x else f"crop={ширина}:{высота}")
    фильтр = (f"[0:v]{GRADE},scale={ширина}:{высота}:force_original_aspect_ratio=increase,"
              f"{обрезка},fps={fps}")
    if zoom:
        frames = max(int(duration * fps), 1)
        zexpr = f"1+{zoom}*on/{frames}" if idx % 2 == 0 else f"{1+zoom}-{zoom}*on/{frames}"
        фильтр += (f",scale={ширина*2}:{высота*2},"
                   f"zoompan=z='{zexpr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                   f"s={ширина}x{высота}:fps={fps}")
    return f"{фильтр}[base];"


def build_piece(src, piece, idx, tmp, стиль):
    start, end = piece["start"], piece["end"]
    duration = end - start
    words = [{"text": w["text"], "start": w["start"] - start, "end": w["end"] - start}
             for w in piece["words"]]
    subs = build_subs_track(words, duration, idx, tmp, стиль)

    out = tmp / f"piece_{idx}.mp4"
    fo = max(duration - 0.012, 0.0)   # микро-фейд на краях — убирает щелчки на стыках склеек
    # лёгкое движение кадра (±4%): чётные куски — наезд, нечётные — отъезд.
    # zoompan по номеру кадра + суперсэмплинг 2× (иначе дрожит на сабпикселях).
    смещение_x = None
    if стиль["монтаж"].get("кадрирование", "лицо") == "лицо":
        try:
            смещение_x = кадрирование.выражение_x(src, start, end)
        except Exception as ошибка:  # noqa: BLE001 - кадрирование не должно ронять сборку
            print(f"кадрирование по лицу пропущено: {ошибка}", file=sys.stderr)
    видеофильтр = фильтр_тела(duration, idx, стиль, смещение_x)
    граф_фильтров = (
        видеофильтр
        + f"[base][1:v]overlay=0:0:eof_action=pass[v];"
        + f"[0:a]afade=t=in:st=0:d=0.012,afade=t=out:st={fo:.3f}:d=0.012[a]"
    )
    run(["ffmpeg", "-y", "-v", "error",
         "-ss", str(start), "-to", str(end), "-i", src, "-i", str(subs),
         "-filter_complex",
         # GRADE 23_06 (под референс Даши): тёплый film — глубже тени, лёгкое тепло, нас.−12%.
         # БЕЗ lut3d. SDR-теги на выходе, чтобы плееры не делали повторный HDR-тонмап.
         граф_фильтров,
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
    return out


def main():
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    стиль = загрузить_стиль(sys.argv[2] if len(sys.argv) > 2 else "Фирменный стиль.md")
    tmp = Path(tempfile.mkdtemp(prefix="reel_"))
    try:
        _собрать(plan, стиль, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _собрать(plan, стиль, tmp):
    pieces = [build_piece(plan["src"], p, i, tmp, стиль) for i, p in enumerate(plan["pieces"])]

    out = Path(plan["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(pieces) == 1:
        # replace(), а не rename(): на Windows rename() падает, если out уже
        # существует (повторный прогон), на macOS/Linux ведёт себя так же.
        pieces[0].replace(out)
    else:
        lst = tmp / "concat.txt"
        lst.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces),
            encoding="utf-8",
        )
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-c", "copy", str(out)])
    dur = sum(p["end"] - p["start"] for p in plan["pieces"])
    print(f"OK {out} ({dur:.1f}s, {len(pieces)} кусков)")


if __name__ == "__main__":
    main()
