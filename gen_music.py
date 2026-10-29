#!/usr/bin/env python3
"""Мягкая эфирная музыкальная подложка (ambient pad, A-major) под рилс.
Синтез numpy — без файлов/лицензий. Тихо (−20 dB), чтобы не глушить голос.

Запуск: python3 gen_music.py <видео> <выход.mp4> [gain]
"""
import subprocess, sys, tempfile, wave
import shutil
import numpy as np
from pathlib import Path

SR = 48000


def run(c): subprocess.run(c, check=True)


def dur(path):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True,
                        text=True, encoding="utf-8")
    return float(o.stdout.strip())


def pad(total):
    """Эфирный пэд: A-major аккорд, лёгкий детюн + медленное дыхание громкости."""
    t = np.linspace(0, total, int(SR * total), endpoint=False)
    notes = [110.0, 164.81, 220.0, 277.18, 329.63]   # A2 E3 A3 C#4 E4
    sig = np.zeros_like(t)
    rng = np.random.default_rng(3)
    for f in notes:
        for det in (-0.3, 0.0, 0.3):                  # хор-детюн для теплоты
            ph = rng.uniform(0, 2*np.pi)
            sig += np.sin(2*np.pi*(f+det)*t + ph) + 0.3*np.sin(2*np.pi*2*(f+det)*t + ph)
    lfo = 0.75 + 0.25*np.sin(2*np.pi*0.08*t)
    fade = int(SR*2.0)
    env = np.ones_like(t)
    env[:fade] = np.linspace(0, 1, fade); env[-fade:] = np.linspace(1, 0, fade)
    sig *= lfo * env
    k = 24; sig = np.convolve(sig, np.ones(k)/k, mode="same")
    sig /= np.max(np.abs(sig)) + 1e-9
    return (sig * 0.9 * 32767).astype(np.int16)


def upbeat(total, bpm=96):
    """Лёгкий лоу-фай-грув: мягкий кик + шейкер + плакающее A-major арпеджио."""
    n = int(SR * total); out = np.zeros(n)
    beat = 60.0 / bpm; rng = np.random.default_rng(5)

    def place(buf, sample, at):
        i = int(at * SR)
        if 0 <= i < n:
            buf[i:i+len(sample)] += sample[:n-i]

    # мягкий кик (низкая синусоида, быстрый спад) на 1 и 3
    kd = 0.18; kt = np.linspace(0, kd, int(SR*kd), endpoint=False)
    kick = np.sin(2*np.pi*(60*np.exp(-kt*12))*kt) * np.exp(-kt*9) * 0.9
    # шейкер (отфильтрованный шум) на каждую долю, тихо
    sd = 0.06; shaker = rng.uniform(-1, 1, int(SR*sd)) * np.exp(-np.linspace(0, sd, int(SR*sd))*55) * 0.18
    # плак (короткая нота с обертоном)
    def pluck(freq):
        pd = 0.34; pt = np.linspace(0, pd, int(SR*pd), endpoint=False)
        return (np.sin(2*np.pi*freq*pt) + 0.4*np.sin(2*np.pi*2*freq*pt)) * np.exp(-pt*6) * 0.4
    arp = [440.0, 554.37, 659.25, 554.37]   # A4 C#5 E5 C#5 — мажор, «весело вверх»
    bars = int(total / beat) + 1
    for b in range(bars):
        tb = b * beat
        if b % 2 == 0: place(out, kick, tb)            # кик на 1 и 3
        place(out, shaker, tb)                          # шейкер каждую долю
        place(out, shaker*0.6, tb + beat/2)             # и на «и»
        place(out, pluck(arp[b % len(arp)]), tb)        # арпеджио по долям
    fade = int(SR*1.2)
    env = np.ones(n); env[:fade] = np.linspace(0, 1, fade); env[-fade:] = np.linspace(1, 0, fade)
    out *= env
    out /= np.max(np.abs(out)) + 1e-9
    return (out * 0.9 * 32767).astype(np.int16)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    gain = float(sys.argv[3]) if len(sys.argv) > 3 else 0.11   # тихо
    style = sys.argv[4] if len(sys.argv) > 4 else "pad"        # pad | upbeat
    tmp = Path(tempfile.mkdtemp(prefix="music_"))
    try:
        wav = tmp / "bed.wav"
        track = upbeat(dur(src)) if style == "upbeat" else pad(dur(src))
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes(track.tobytes())
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-i", str(wav),
             "-filter_complex",
             f"[1:a]volume={gain}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", dst])
        print(f"OK {dst} (подложка, gain={gain})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
