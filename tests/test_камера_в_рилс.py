"""Замена звука окна камеры звуком петличек по шкале мастера."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from камера_в_рилс import заменить_звук  # noqa: E402


def _длительность(путь: Path, поток: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", поток, "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(путь)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def test_звук_окна_берётся_из_источника(tmp_path: Path) -> None:
    часть = tmp_path / "окно.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3", "-f", "lavfi",
                    "-i", "sine=frequency=200:duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(часть)],
                   check=True)
    источник = tmp_path / "петлички.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:duration=10", str(источник)],
                   check=True)
    заменить_звук(часть, str(источник), 2.0, 5.0)
    assert часть.exists()
    assert abs(_длительность(часть, "a:0") - 3.0) < 0.2
    assert abs(_длительность(часть, "v:0") - 3.0) < 0.2
    assert not (tmp_path / "окно_звук.mp4").exists()
