"""Findings of the phase B re-review: D02 guard holes, tool faults, unpinned checks."""

import json
from pathlib import Path

import pytest

from reel_studio.cli import reel
from reel_studio.core import config
from reel_studio.editor.media import edl, pipeline, qa
from reel_studio.editor.media.render import PlacedText
from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings
from tests.unit.editor.test_edl import _check, _edl

# Passes precheck, so only the --out guard can stop it before the pipeline.
VALID = {"versions": [{"name": "A", "segments": [{"clip": "c01", "in": 0, "out": 1}]}]}


def _settings(make_settings: MakeSettings) -> EditorSettings:
    settings = make_settings(EditorSettings)
    assert isinstance(settings, EditorSettings)
    return settings


def _never_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: object) -> None:
        raise AssertionError("the --out guard let the pipeline run")

    monkeypatch.setattr(pipeline, "build_shots", fail)


def _run(tmp_path: Path, folder: Path, out: Path, settings: EditorSettings) -> int:
    edl_file = tmp_path / "edl.json"
    edl_file.write_text(json.dumps(VALID), encoding="utf-8")
    return reel.main(["render", "--edl", str(edl_file), str(folder), "--out", str(out)], settings)


@pytest.mark.parametrize("inside", ["", "sub", "sub/deeper"])
def test_out_inside_the_folder_stops_before_the_pipeline(
    tmp_path: Path, make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch, inside: str
) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    _never_builds(monkeypatch)

    out = folder / inside if inside else folder
    assert _run(tmp_path, folder, out, _settings(make_settings)) == 2


def test_a_folder_named_work_under_out_is_refused(
    tmp_path: Path, make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "work"  # out/work would be the input folder itself
    folder.mkdir()
    _never_builds(monkeypatch)

    assert _run(tmp_path, folder, tmp_path, _settings(make_settings)) == 2


def test_a_case_variant_spelling_of_the_folder_is_refused(
    tmp_path: Path, make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "CaseDir"
    folder.mkdir()
    variant = tmp_path / "casedir"
    if not variant.exists():
        pytest.skip("case-sensitive file system: the variant is another folder")
    _never_builds(monkeypatch)

    assert _run(tmp_path, folder, variant / "out", _settings(make_settings)) == 2


def test_empty_label_is_no_text_as_in_the_kit() -> None:
    raw = _edl()
    raw["versions"][0]["segments"][1]["text"] = ""

    assert _check(raw).errors == []


@pytest.mark.parametrize(
    ("change", "warning"),
    [("labels", "reads as clutter"), ("format", "target")],
)
def test_more_craft_warnings(change: str, warning: str) -> None:
    raw = _edl()
    if change == "labels":
        for seg in raw["versions"][0]["segments"]:
            seg["text"] = "Label"
        raw["versions"][0]["segments"] = raw["versions"][0]["segments"] * 3
    else:
        raw["format"] = "pov"  # the 7 s cut is below pov's 10-30 s target

    assert any(warning in w for w in _check(raw).warnings)


def test_text_outside_the_safe_zone_fails_its_hard_check() -> None:
    box = PlacedText(
        text="x",
        kind="step",
        position="top",
        start=0.0,
        end=1.0,
        x0=0,
        y0=0,
        x1=10,
        y1=10,
        font_px=60,
        lines=1,
        inside_safe_zone=False,
    )

    assert qa.all_inside([box]) is False
    assert qa.all_inside([]) is True


def test_precheck_reports_shape_errors_without_clips() -> None:
    raw = {"versions": [], "audio": {"music": "x"}}

    early = edl.precheck(raw, config.load_media())

    assert early
