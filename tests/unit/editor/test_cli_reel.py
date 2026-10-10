"""`reel render` refuses bad arguments before any ffmpeg work (STEP-02 task 4)."""

import json
from pathlib import Path

import pytest

from reel_studio.cli import reel
from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings


def _settings(make_settings: MakeSettings) -> EditorSettings:
    settings = make_settings(EditorSettings)
    assert isinstance(settings, EditorSettings)
    return settings


def test_render_help_names_its_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as done:
        reel.main(["render", "--help"])

    assert done.value.code == 0
    out = capsys.readouterr().out
    assert "--edl" in out and "--out" in out


def test_missing_folder_exits_2(tmp_path: Path, make_settings: MakeSettings) -> None:
    edl = tmp_path / "edl.json"
    edl.write_text("{}", encoding="utf-8")

    code = reel.main(
        ["render", "--edl", str(edl), str(tmp_path / "nope")], _settings(make_settings)
    )

    assert code == 2


def test_edl_that_is_not_json_exits_2(tmp_path: Path, make_settings: MakeSettings) -> None:
    edl = tmp_path / "edl.json"
    edl.write_text("{not json", encoding="utf-8")
    folder = tmp_path / "in"
    folder.mkdir()

    code = reel.main(["render", "--edl", str(edl), str(folder)], _settings(make_settings))

    assert code == 2


def test_out_defaults_next_to_the_folder_never_inside_it(tmp_path: Path) -> None:
    folder = tmp_path / "Pistachio cookies"

    out = reel.default_out(folder)

    assert out == tmp_path / "Pistachio cookies-reel"
    assert folder not in out.parents


def test_edl_json_is_read_not_written(tmp_path: Path, make_settings: MakeSettings) -> None:
    edl = tmp_path / "edl.json"
    # Odd spacing, and an error the precheck finds only after reading: exit 2 proves the read.
    text = '{ "versions":[],   "audio": {"music": "song.mp3"} }\n'
    edl.write_text(text, encoding="utf-8")
    folder = tmp_path / "in"
    folder.mkdir()

    code = reel.main(["render", "--edl", str(edl), str(folder)], _settings(make_settings))

    assert code == 2
    assert edl.read_bytes() == text.encode("utf-8")


def test_dot_as_the_folder_names_the_default_out_from_the_real_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "cookies"
    folder.mkdir()
    monkeypatch.chdir(folder)

    assert reel.default_out(Path(".")) == tmp_path / "cookies-reel"


def test_utf16_edl_exits_2(tmp_path: Path, make_settings: MakeSettings) -> None:
    edl = tmp_path / "edl.json"
    edl.write_text("{}", encoding="utf-16")
    folder = tmp_path / "in"
    folder.mkdir()

    assert reel.main(["render", "--edl", str(edl), str(folder)], _settings(make_settings)) == 2


def test_edl_errors_that_need_no_clips_exit_2_before_any_ffmpeg_work(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    edl = tmp_path / "edl.json"
    edl.write_text(json.dumps({"versions": [], "audio": {"music": "song.mp3"}}), encoding="utf-8")
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.mov").write_bytes(b"not a video")
    # ffmpeg paths do not exist: any ffmpeg call would fail differently
    settings = _settings(make_settings)

    assert reel.main(["render", "--edl", str(edl), str(folder)], settings) == 2
    assert not reel.default_out(folder).exists()
