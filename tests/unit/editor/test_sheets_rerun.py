"""A rerun with fewer clips must not leave old sheets behind (kit prep.py:170-171)."""

import logging
from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.editor.media import prepare, sheets


def test_stale_sheets_are_removed_on_rebuild(tmp_path: Path) -> None:
    out = tmp_path / "sheets"
    out.mkdir()
    (out / "sheet07.jpg").write_bytes(b"old")

    paths, legend = sheets.build(
        tmp_path, [], out, config.load().limits.sheets, config.load_media()
    )

    assert (paths, legend) == ([], [])
    assert not (out / "sheet07.jpg").exists()


def test_every_style_photo_left_out_of_the_footage_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "IMG_1_vsco.jpg").touch()
    (tmp_path / "IMG_2.jpg").touch()
    caplog.set_level(logging.INFO, logger="reel_studio")

    files = prepare.footage(tmp_path, config.load_media().grade.reference_words)

    assert [p.name for p in files] == ["IMG_2.jpg"]
    assert any("IMG_1_vsco.jpg" in r.getMessage() for r in caplog.records)
