#!/usr/bin/env python3
"""Финальная полировка рилса: цветокор «как артефакт» (тёмно-лесная зелень,
тёплые кремовые хайлайты, мягкая виньетка) + волшебный перезвон-искорки на хопе.

Перезвон синтезируется numpy (без файлов/лицензий). Синхрон по времени хопа.

Запуск: python3 gen_polish.py cut/19_06_05_final.mp4 cut/19_06_05_polished.mp4 [hop_sec]
"""
import subprocess, sys, tempfile
import numpy as np
from pathlib import Path

SR = 48000
# лёгкий грейд: без виньетки, вдвое мягче — чтобы при пересжатии платформой
# (Telegram/IG докручивают свой фильтр) не выглядело переобработанным
GRADE = ("eq=contrast=1.03:saturation=1.02:brightness=-0.005,"
         "colorbalance=gs=0.03:bs=-0.02:gm=0.015:rh=0.03:bh=-0.025")


def run(c): subprocess.run(c, check=True)


def bell(freq, dur, amp=0.5):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    # колокол: основной тон + обертоны, экспоненциальный спад
    env = np.exp(-t * 5.5)
    sig = (np.sin(2*np.pi*freq*t)
           + 0.5*np.sin(2*np.pi*2*freq*t)
           + 0.25*np.sin(2*np.pi*3.01*freq*t))
    return amp * env * sig


def chime():
    """Восходящее арпеджио-перезвон (A5 C#6 E6 A6) + высокие искорки."""
    total = 1.6
    out = np.zeros(int(SR * total))
    notes = [(880.0, 0.00), (1108.7, 0.07), (1318.5, 0.14), (1760.0, 0.22)]
    for f, t0 in notes:
        b = bell(f, 1.2, amp=0.42)
        i = int(SR * t0)
        out[i:i+len(b)] += b[:len(out)-i]
    # искорки-шиммер: короткие высокие блипы
    rng = np.random.default_rng(7)
    for _ in range(14):
        f = rng.uniform(2600, 5200); t0 = rng.uniform(0.05, 1.0); d = 0.08
        tt = np.linspace(0, d, int(SR*d), endpoint=False)
        blip = 0.10*np.exp(-tt*40)*np.sin(2*np.pi*f*tt)
        i = int(SR*t0); out[i:i+len(blip)] += blip[:len(out)-i]
    out /= np.max(np.abs(out)) + 1e-9
    return (out * 0.6 * 32767).astype(np.int16)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    hop = float(sys.argv[3]) if len(sys.argv) > 3 else 50.5
    if hop < 0:
        # Финала нет: перезвон не нужен, звук и видео копируются как есть.
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c", "copy", dst])
        print(f"OK {dst} (без грейда и без перезвона: финал отключён)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="polish_"))
    import wave
    wav = tmp / "chime.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(chime().tobytes())
    delay = int(hop * 1000)
    # БЕЗ цветокора — оригинальный цвет (видео копируется), только перезвон в аудио
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-i", str(wav),
         "-filter_complex",
         f"[1:a]adelay={delay}|{delay}[c];"
         f"[0:a][c]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", dst])
    print(f"OK {dst} (без грейда, перезвон на {hop:.1f}с)")


if __name__ == "__main__":
    main()
