"""Стражи формы команд ffmpeg без запуска ffmpeg и обработки видео."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import gen_cover
import gen_finale
import gen_music
import gen_polish
import gen_scheme
import stitch_reel

from стиль import УМОЛЧАНИЯ


ФЛАГИ_ФИЛЬТРОВ = {"-filter_complex", "-vf", "-af", "-lavfi"}


class _ПустойКадр:
    def save(self, _путь):
        pass


def _отдельная_папка(tmp_path, prefix):
    """Каждый модуль получает свою временную папку: после сборки модуль её убирает."""
    папка = tmp_path / prefix
    папка.mkdir(exist_ok=True)
    return папка


def _стиль_с_зумом(зум):
    стиль = deepcopy(УМОЛЧАНИЯ)
    стиль["монтаж"]["зум"] = зум
    return стиль


def _команда_куска(monkeypatch, tmp_path: Path, зум):
    команды = []
    monkeypatch.setattr(stitch_reel, "build_subs_track", lambda *_: tmp_path / "subs.mov")
    monkeypatch.setattr(stitch_reel, "run", команды.append)
    stitch_reel.build_piece(
        "исходник.mp4",
        {"start": 1.0, "end": 3.0, "words": []},
        0,
        tmp_path,
        _стиль_с_зумом(зум),
    )
    return команды[0]


def _команды_всех_модулей(monkeypatch, tmp_path: Path):
    команды = {}

    команды["stitch_reel"] = [_команда_куска(monkeypatch, tmp_path, 0.08)]

    финал = []
    monkeypatch.setattr(gen_finale, "загрузить_стиль", lambda _: {
        "формат": {"кадров_в_секунду": 1},
        "финал": {"подпись": "Подпись"},
    })
    monkeypatch.setattr(gen_finale, "dur", lambda _: 2.0)
    monkeypatch.setattr(gen_finale.tempfile, "mkdtemp", lambda prefix: str(_отдельная_папка(tmp_path, prefix)))
    monkeypatch.setattr(gen_finale, "frame", lambda *_: _ПустойКадр())
    monkeypatch.setattr(gen_finale, "run", финал.append)
    monkeypatch.setattr(sys, "argv", ["gen_finale.py", "вход.mp4", "выход.mp4"])
    assert gen_finale.main() is True
    команды["gen_finale"] = финал

    обложка = []
    monkeypatch.setattr(gen_cover, "параметры_обложки", lambda *_: {
        "длительность": 2.2,
        "затухание": 0.4,
    })
    monkeypatch.setattr(gen_cover.tempfile, "mkdtemp", lambda prefix: str(_отдельная_папка(tmp_path, prefix)))
    monkeypatch.setattr(gen_cover, "overlay_png", lambda *_: None)
    monkeypatch.setattr(gen_cover, "run", обложка.append)
    monkeypatch.setattr(sys, "argv", ["gen_cover.py", "ролик.md", "вход.mp4", "выход.mp4"])
    gen_cover.main()
    команды["gen_cover"] = обложка

    музыка = []
    monkeypatch.setattr(gen_music, "dur", lambda _: 0.0)
    monkeypatch.setattr(gen_music, "pad", lambda _: gen_music.np.zeros(1, dtype="int16"))
    monkeypatch.setattr(gen_music.tempfile, "mkdtemp", lambda prefix: str(_отдельная_папка(tmp_path, prefix)))
    monkeypatch.setattr(gen_music, "run", музыка.append)
    monkeypatch.setattr(sys, "argv", ["gen_music.py", "вход.mp4", "выход.mp4"])
    gen_music.main()
    команды["gen_music"] = музыка

    полировка = []
    monkeypatch.setattr(gen_polish, "chime", lambda: gen_polish.np.zeros(1, dtype="int16"))
    monkeypatch.setattr(gen_polish.tempfile, "mkdtemp", lambda prefix: str(_отдельная_папка(tmp_path, prefix)))
    monkeypatch.setattr(gen_polish, "run", полировка.append)
    monkeypatch.setattr(sys, "argv", ["gen_polish.py", "вход.mp4", "выход.mp4"])
    gen_polish.main()
    команды["gen_polish"] = полировка

    схема = []

    def subprocess_run(команда, **_kwargs):
        if команда[0] == "ffprobe":
            return SimpleNamespace(stdout="5.0")
        схема.append(команда)
        return SimpleNamespace()

    monkeypatch.setattr(gen_scheme, "panel_png", lambda *_: None)
    monkeypatch.setattr(gen_scheme.tempfile, "mkdtemp", lambda prefix: str(_отдельная_папка(tmp_path, prefix)))
    monkeypatch.setattr(gen_scheme.subprocess, "run", subprocess_run)
    monkeypatch.setattr(gen_scheme, "загрузить_стиль", lambda _: _стиль_с_зумом(0.08))
    monkeypatch.setattr(sys, "argv", ["gen_scheme.py", "premium1", "вход.mp4", "выход.mp4"])
    gen_scheme.main()
    команды["gen_scheme"] = схема

    return команды


def _проверить_форму_фильтров(команда):
    for номер, аргумент in enumerate(команда):
        if аргумент not in ФЛАГИ_ФИЛЬТРОВ:
            continue
        assert номер + 2 < len(команда), f"{аргумент} должен иметь ровно один аргумент"
        фильтр = команда[номер + 1]
        assert isinstance(фильтр, str) and not фильтр.startswith("-"), (
            f"после {аргумент} должен идти один аргумент фильтра"
        )
        assert команда[номер + 2].startswith("-"), (
            f"после единственного аргумента {аргумент} ожидается следующий флаг"
        )

    for номер, аргумент in enumerate(команда):
        if isinstance(аргумент, str) and аргумент.startswith("["):
            # Метки допустимы только внутри единственного аргумента графа и
            # в значениях -map. Метка после другого аргумента означает, что
            # граф по ошибке разорвали запятой в списке команды.
            assert номер > 0 and команда[номер - 1] in {"-filter_complex", "-map"}, (
                f"отдельный фрагмент графа {аргумент!r} не должен быть аргументом ffmpeg"
            )


def test_все_модули_передают_целые_фильтры_ffmpeg(monkeypatch, tmp_path: Path):
    команды = _команды_всех_модулей(monkeypatch, tmp_path)

    assert set(команды) == {
        "stitch_reel", "gen_finale", "gen_cover", "gen_music", "gen_polish", "gen_scheme",
    }
    for команды_модуля in команды.values():
        for команда in команды_модуля:
            _проверить_форму_фильтров(команда)

    фильтр_куска = команды["stitch_reel"][0]
    фильтр_куска = фильтр_куска[фильтр_куска.index("-filter_complex") + 1]
    assert "[base]" in фильтр_куска
    assert "overlay" in фильтр_куска


def test_нулевой_зум_не_добавляет_zoompan_в_команду(monkeypatch, tmp_path: Path):
    команда = _команда_куска(monkeypatch, tmp_path, 0)
    фильтр = команда[команда.index("-filter_complex") + 1]

    assert "zoompan" not in фильтр


def test_разные_значения_зума_дают_разные_команды(monkeypatch, tmp_path: Path):
    малая = _команда_куска(monkeypatch, tmp_path, 0.03)
    большая = _команда_куска(monkeypatch, tmp_path, 0.11)

    assert малая != большая
