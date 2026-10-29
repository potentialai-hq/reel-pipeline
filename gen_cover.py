#!/usr/bin/env python3
"""Хук-обложка (стиль B) поверх первых ~2с рилса: вуаль + 2 строки
(кремовый Unbounded + золотой Cormorant) + искорки + стикер-маскот под акцентом.
Уходит фейдом на 2с — дальше живой кадр.

Запуск: python3 gen_cover.py <ролик.md> <вход.mp4> <выход.mp4> [Фирменный стиль.md]
"""
import sys, subprocess, math, random, tempfile
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ролик import загрузить_ролик
from стиль import загрузить_стиль, цвет

W, H = 1080, 1920
ШРИФТЫ = Path("assets/fonts")
СТИКЕРЫ = Path("assets/stickers")

def run(c): subprocess.run(c, check=True)


def _путь_шрифта(имя: str) -> str:
    """Возвращает путь к шрифту из ассетов или явно заданный путь.

    Строка всегда с прямым слэшем (as_posix): и наши конфиги/тесты, и ffmpeg
    ждут его на любой платформе, а Windows прекрасно читает файлы и по нему.
    """
    путь = Path(имя)
    if путь.parent == Path("."):
        путь = ШРИФТЫ / путь
    return путь.as_posix()


def параметры_обложки(путь_ролика, путь_стиля="Фирменный стиль.md"):
    """Собирает текст ролика и оформление обложки из двух Markdown-файлов."""
    обложка_ролика = загрузить_ролик(путь_ролика)["обложка"]
    обложка_стиля = загрузить_стиль(путь_стиля)["обложка"]
    return {
        "строка1": обложка_ролика["строка1"],
        "строка2": обложка_ролика["строка2"],
        "стикер": обложка_ролика["стикер"],
        "позиция": обложка_стиля["позиция"],
        "длительность": обложка_стиля["длительность"],
        "затухание": обложка_стиля["затухание"],
        "шрифт_основной": _путь_шрифта(обложка_стиля["шрифт_основной"]),
        "шрифт_акцента": _путь_шрифта(обложка_стиля["шрифт_акцента"]),
        "цвет_основной": цвет(обложка_стиля["цвет_основной"]),
        "цвет_акцента": цвет(обложка_стиля["цвет_акцента"]),
        "стикеры": обложка_стиля["стикеры"],
    }


def fit(path, text, target, maxw=W - 110):
    s = target; f = ImageFont.truetype(path, s)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    while d.textlength(text, font=f) > maxw and s > 40:
        s -= 4; f = ImageFont.truetype(path, s)
    return f, s


def shadow(im, t, f, cx, y, fill, off=(5, 8), blur=14, sa=200):
    d = ImageDraw.Draw(im); w = d.textlength(t, font=f); x = cx - w / 2
    s = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(s).text((x + off[0], y + off[1]), t, font=f, fill=(0, 0, 0, sa))
    im.alpha_composite(s.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(im).text((x, y), t, font=f, fill=fill)
    return x, w


def stars(im, seed, cy, основной, акцентный, n=12, spread=360):
    rnd = random.Random(seed); d = ImageDraw.Draw(im)
    for i in range(n):
        a = rnd.uniform(0, 6.28); r = rnd.uniform(0.4, 1) * spread
        x = W / 2 + math.cos(a) * r; y = cy + math.sin(a) * r * 0.5; s = rnd.uniform(5, 12)
        c = (акцентный if i % 2 else основной) + (rnd.randint(120, 210),)
        d.polygon([(x, y-s), (x+s*0.3, y-s*0.3), (x+s, y), (x+s*0.3, y+s*0.3),
                   (x, y+s), (x-s*0.3, y+s*0.3), (x-s, y), (x-s*0.3, y-s*0.3)], fill=c)


def _стикер(имя):
    """Читает стикер, если он включён и существует в необязательной папке."""
    if not isinstance(имя, str) or not имя.strip():
        return None
    путь = СТИКЕРЫ / f"{имя}.png"
    return Image.open(путь).convert("RGBA") if путь.is_file() else None


def overlay_png(параметры, path):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov.alpha_composite(Image.new("RGBA", (W, H), (10, 22, 15, 105)))   # вуаль (только на обложке 0–2с)
    Y1 = int(H * float(параметры["позиция"]))   # верх названия: доля высоты из стиля (0.40 центр, 0.56 низ)
    строка1, строка2 = параметры["строка1"], параметры["строка2"]
    stars(ov, hash((строка1, строка2)) & 255, Y1 + 120,
          параметры["цвет_основной"], параметры["цвет_акцента"])
    f1, s1 = fit(параметры["шрифт_основной"], строка1, 72)
    try: f1.set_variation_by_axes([800])
    except Exception: pass
    shadow(ov, строка1, f1, W // 2, Y1, параметры["цвет_основной"])
    Y2 = Y1 + int(s1 * 0.67)                                            # плотный межстрочный
    f2, s2 = fit(параметры["шрифт_акцента"], строка2, 150)
    x2, _ = shadow(ov, строка2, f2, W // 2, Y2, параметры["цвет_акцента"], off=(5, 8), blur=16)
    st = _стикер(параметры["стикер"]) if параметры["стикеры"] else None
    if st is not None:
        fh = 200; fw = int(st.width * fh / st.height); st = st.resize((fw, fh))
        ov.alpha_composite(st, (int(x2 - fw * 0.15), Y2 + s2 - 40))
    ov.save(path)


def main():
    путь_ролика, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    параметры = параметры_обложки(
        путь_ролика,
        sys.argv[4] if len(sys.argv) > 4 else "Фирменный стиль.md",
    )
    tmp = Path(tempfile.mkdtemp(prefix="cover_"))
    try:
        png = tmp / "cover.png"
        overlay_png(параметры, png)
        длительность, затухание = параметры["длительность"], параметры["затухание"]
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-loop", "1", "-t", str(длительность), "-i", str(png),
             "-filter_complex",
             f"[1:v]format=rgba,fade=t=out:st={длительность-затухание}:d={затухание}:alpha=1[ov];"
             f"[0:v][ov]overlay=0:0:enable='lte(t,{длительность})'[v]",
             "-map", "[v]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "copy", dst])
        print(f"OK обложка -> {dst}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
