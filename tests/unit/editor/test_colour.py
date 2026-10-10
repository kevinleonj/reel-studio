"""Per-frame colour statistics in Lab and their clip-level merge (kit grade.py:37-58)."""

import numpy as np
import pytest

from reel_studio.core import config
from reel_studio.editor.media import colour

SIZE = (320, 180, 3)  # a portrait frame, rows x cols x BGR


def _frame(bgr: tuple[int, int, int]) -> np.ndarray:
    return np.full(SIZE, bgr, dtype=np.uint8)


def test_grey_frame_is_all_neutral_with_no_cast() -> None:
    stats = colour.frame_stats(_frame((128, 128, 128)), config.load_media().grade.stats)

    assert stats.neutral_frac == pytest.approx(1.0)
    assert stats.neutral_ab is not None
    assert all(abs(v) < 1.0 for v in stats.neutral_ab)
    assert stats.p2 == pytest.approx(stats.p98, abs=0.01)


def test_saturated_frame_has_no_white_balance_estimate() -> None:
    stats = colour.frame_stats(_frame((0, 0, 255)), config.load_media().grade.stats)

    assert stats.neutral_frac == 0.0
    assert stats.neutral_ab is None


def test_merge_of_identical_frames_is_that_frame() -> None:
    one = colour.frame_stats(_frame((60, 120, 200)), config.load_media().grade.stats)

    merged = colour.merge([one, one, one])

    assert merged.p50 == pytest.approx(one.p50)
    assert merged.mean == pytest.approx(one.mean)


def test_merge_of_nothing_fails() -> None:
    with pytest.raises(ValueError, match="no frames"):
        colour.merge([])


def test_colourfulness_of_grey_is_zero() -> None:
    assert colour.colourfulness(_frame((90, 90, 90))) == pytest.approx(0.0)
