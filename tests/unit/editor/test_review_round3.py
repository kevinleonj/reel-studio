"""Round-3 re-review: the tool check must be what fails, and the guard works both ways."""

import json
from pathlib import Path

import pytest

from reel_studio.cli import reel
from reel_studio.core import config
from reel_studio.core.errors import NoUsableInput, RenderError
from reel_studio.editor.media import pipeline, prepare, tools
from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings

VALID = {"versions": [{"name": "A", "segments": [{"clip": "c01", "in": 0, "out": 1}]}]}
RUNNABLE = 0o755


def _stand_in(folder: Path, name: str, exit_code: int) -> Path:
    """A binary that starts and exits with `exit_code`, whatever it is asked."""
    script = folder / name
    script.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    script.chmod(RUNNABLE)
    return script


def _one_video(tmp_path: Path) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "IMG_1.MOV").write_bytes(b"mov")
    return folder


def test_missing_ffprobe_beside_a_working_ffmpeg_is_a_tool_error(tmp_path: Path) -> None:
    ffmpeg = _stand_in(tmp_path, "ffmpeg", 0)
    broken = tools.Ffmpeg(ffmpeg, tmp_path / "nope" / "ffprobe", config.load_media().tools)

    with pytest.raises(RenderError, match="check ffprobe: cannot start") as caught:
        prepare.prepare_folder(_one_video(tmp_path), tmp_path / "w", broken, config.load_media())

    assert not isinstance(caught.value, NoUsableInput)


def test_a_tool_that_starts_but_fails_its_version_check_is_a_tool_error(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _stand_in(tmp_path, "ffmpeg", 0), _stand_in(tmp_path, "ffprobe", 1)
    broken = tools.Ffmpeg(ffmpeg, ffprobe, config.load_media().tools)

    with pytest.raises(RenderError, match="-version exited 1"):
        prepare.prepare_folder(_one_video(tmp_path), tmp_path / "w", broken, config.load_media())


def _settings(make_settings: MakeSettings) -> EditorSettings:
    settings = make_settings(EditorSettings)
    assert isinstance(settings, EditorSettings)
    return settings


def test_a_folder_inside_out_work_is_refused(
    tmp_path: Path, make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    folder = out / reel.WORK / "clips"  # a previous run's proxies used as input
    folder.mkdir(parents=True)

    def fail(*_: object) -> None:
        raise AssertionError("the --out guard let the pipeline run")

    monkeypatch.setattr(pipeline, "build_shots", fail)
    edl = tmp_path / "edl.json"
    edl.write_text(json.dumps(VALID), encoding="utf-8")

    code = reel.main(
        ["render", "--edl", str(edl), str(folder), "--out", str(out)], _settings(make_settings)
    )

    assert code == 2
