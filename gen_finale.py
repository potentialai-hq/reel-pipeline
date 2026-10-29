#!/usr/bin/env python3
"""Анимированный финал-хоп для рилса: волшебное появление подписи из стиля
(Cormorant Garamond Italic, кремовый + тень + золотой контур) + искорки + «Псшш!».

Схема: PNG-секвенция (Pillow, с частотой из фирменного стиля) -> прозрачный mov
-> overlay поверх рилса
(с хвостом-фризом, чтобы подпись подержалась). Зависимостей сверх pillow/ffmpeg нет.

Запуск: python3 gen_finale.py <вход.mp4> <выход.mp4> [Фирменный стиль.md]
"""
import math, random, subprocess, sys, tempfile
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from стиль import кадров_в_секунду, загрузить_стиль

W, H = 1080, 1920
CREAM = (245, 240, 225); GOLD = (255, 210, 63)
SIG = "assets/fonts/CormorantGaramondItalic.ttf"

TAIL = 1.0            # хвост-фриз (с) после конца речи/пшш
HOP_BEFORE_END = 2.0 # за сколько до конца базы начинается хоп
REVEAL = 0.7         # длительность раскрытия подписи
PSH_AT = 1.4         # локальное время «Псшш!» (синхронно с реальным пшш в финале)
SIG_Y = 1000         # центр подписи по вертикали
SIG_SIZE = 200


def run(cmd): subprocess.run(cmd, check=True)
def ease(t): return 1 - (1 - t) ** 3


def star(d, cx, cy, r, col, a):
    d.polygon([(cx, cy-r), (cx+r*0.28, cy-r*0.28), (cx+r, cy), (cx+r*0.28, cy+r*0.28),
               (cx, cy+r), (cx-r*0.28, cy+r*0.28), (cx-r, cy), (cx-r*0.28, cy-r*0.28)],
              fill=col + (a,))


def sparkles(layer, prog, cy, n=22, spread=420, seed=7):
    rnd = random.Random(seed); d = ImageDraw.Draw(layer)
    for i in range(n):
        ang = rnd.uniform(0, 2*math.pi); dist = rnd.uniform(0.25, 1) * spread
        r = dist * ease(min(prog*1.3, 1))
        x = W/2 + math.cos(ang)*r; y = cy + math.sin(ang)*r*0.55
        life = max(0, min(1, (prog - rnd.uniform(0, 0.35)) * 2))
        a = int(255 * (1 - abs(life-0.5)*2)) if life > 0 else 0
        if a > 5:
            star(d, x, y, rnd.uniform(8, 20)*(0.5+0.5*prog), GOLD if i % 3 else CREAM, a)


FILL = GOLD                  # цвет букв (вариант 3: золото)
GLOW = (255, 255, 255)       # цвет свечения по контуру (белое)


def подпись_финала(стиль):
    """Возвращает подпись финала из фирменного стиля.

    Пустая подпись означает, что фирменный финал для ролика отключён.
    """
    финал = стиль.get("финал", {})
    подпись = финал.get("подпись", "") if isinstance(финал, dict) else ""
    return подпись.strip() if isinstance(подпись, str) else ""


def параметры_анимации(длительность, стиль):
    """Возвращает частоту и количество кадров финала из фирменного стиля."""
    fps = кадров_в_секунду(стиль)
    return fps, int(длительность * fps)


def sig_text(layer, text, f, cx, y, a):
    """Свечение по контуру (мягкое гало) + лёгкая тень. Без жёсткой обводки."""
    d = ImageDraw.Draw(layer); w = d.textlength(text, font=f); x = cx - w/2
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(base).text((x, y), text, font=f, fill=GLOW + (255,))
    for rad, al in [(26, 90), (14, 130), (6, 170)]:       # гало в три прохода
        g = base.filter(ImageFilter.GaussianBlur(rad))
        g.putalpha(g.split()[3].point(lambda v: int(v * al / 255 * a / 255)))
        layer.alpha_composite(g)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))           # лёгкая тень для читаемости
    ImageDraw.Draw(sh).text((x+3, y+5), text, font=f, fill=(0, 0, 0, int(150*a/255)))
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    ImageDraw.Draw(layer).text((x, y), text, font=f, fill=FILL + (a,))


def frame(t, подпись):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sparkles(lay, min(t/REVEAL, 1), cy=SIG_Y)
    a = int(255 * min(t/(REVEAL*0.55), 1)); scale = 0.55 + 0.45*ease(min(t/REVEAL, 1))
    size = int(SIG_SIZE*scale); f = ImageFont.truetype(SIG, size)
    drift = int(34*(1-ease(min(t/REVEAL, 1))))
    sig_text(lay, подпись, f, W//2, SIG_Y + drift - size//2, a)
    if t > PSH_AT:
        ap = int(255*min((t-PSH_AT)/0.3, 1)); fp = ImageFont.truetype(SIG, 110)
        sig_text(lay, "Псшш!", fp, W//2, SIG_Y + 220, ap)
        sparkles(lay, (t-PSH_AT)/0.4, cy=SIG_Y+280, n=10, spread=200, seed=21)
    return lay


def dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True,
                          text=True, encoding="utf-8")
    return float(out.stdout.strip())


def main():
    src, dst = sys.argv[1], sys.argv[2]
    стиль = загрузить_стиль(sys.argv[3] if len(sys.argv) > 3 else "Фирменный стиль.md")
    подпись = подпись_финала(стиль)
    if not подпись:
        print("Финал пропущен: в фирменном стиле не заполнена подпись")
        return False
    base = dur(src)
    tmp = Path(tempfile.mkdtemp(prefix="finale_"))
    try:

        hop = base - HOP_BEFORE_END                 # абсолютный старт хопа в рилсе

        # 1) хвост-фриз: клонируем последний кадр + тишина (пшш уже в аудио финала)
        ext = tmp / "ext.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", src,
             "-vf", f"tpad=stop_mode=clone:stop_duration={TAIL}",
             "-af", f"apad=pad_dur={TAIL}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", str(ext)])
        fin_dur = (base + TAIL) - hop               # длительность анимации
        fps, n = параметры_анимации(fin_dur, стиль)
        for i in range(n):
            frame(i / fps, подпись).save(tmp / f"f{i:04d}.png")
        mov = tmp / "finale.mov"
        run(["ffmpeg", "-y", "-v", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
             "-c:v", "png", str(mov)])

        # 2) overlay со смещением
        run(["ffmpeg", "-y", "-v", "error", "-i", str(ext), "-itsoffset", f"{hop:.3f}", "-i", str(mov),
             "-filter_complex", f"[0:v][1:v]overlay=0:0:eof_action=pass:enable='gte(t,{hop:.3f})'[v]",
             "-map", "[v]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "copy", dst])
        print(f"OK {dst}  (хоп с {hop:.2f}s, анимация {fin_dur:.2f}s, итог {base+TAIL:.2f}s)")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
