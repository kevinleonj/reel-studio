"""Style photos (kit grade.py:61-73): sized from the header first, never decoded past the cap."""

from pathlib import Path

import cv2
import pytest
from PIL import Image

from reel_studio.core import config
from reel_studio.editor.media import colour

GRADE = config.load_media().grade


def test_a_style_photo_over_the_pixel_cap_is_skipped_before_it_is_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    Image.new("RGB", (20, 20), (200, 120, 60)).save(tmp_path / "look_small.jpg")
    Image.new("RGB", (40, 30), (20, 20, 20)).save(tmp_path / "ref_big.png")
    decoded: list[str] = []
    real_imread = cv2.imread

    def imread(path: str) -> object:
        decoded.append(Path(path).name)
        return real_imread(path)

    monkeypatch.setattr(cv2, "imread", imread)

    with caplog.at_level("WARNING"):
        stats, used = colour.reference_stats(tmp_path, GRADE.reference_words, GRADE.stats, 1_000)

    assert stats is not None and used == ["look_small.jpg"]
    assert decoded == ["look_small.jpg"]  # REVIEW-FIXES engine item 3
    assert any("ref_big.png" in r.getMessage() for r in caplog.records)


def test_a_style_photo_whose_header_cannot_be_read_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "vsco_broken.jpg").write_bytes(b"not a jpeg")

    with caplog.at_level("WARNING"):
        stats, used = colour.reference_stats(
            tmp_path, GRADE.reference_words, GRADE.stats, config.load_media().prepare.max_pixels
        )

    assert stats is None and used == []
    assert any("vsco_broken.jpg" in r.getMessage() for r in caplog.records)
