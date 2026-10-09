"""Windows inside a clip (kit prep.py:125-128)."""

import pytest

from reel_studio.core import config
from reel_studio.editor.media import measure


def test_long_take_splits_into_at_most_24_contiguous_windows() -> None:
    cfg = config.load_media().measure

    windows = measure.split_windows(0.0, 90.0, cfg)

    assert len(windows) == cfg.max_windows_per_clip
    assert windows[0][0] == 0.0 and windows[-1][1] == pytest.approx(90.0)
    ends, starts = [w[1] for w in windows[:-1]], [w[0] for w in windows[1:]]
    assert ends == pytest.approx(starts)


def test_short_shot_is_one_window() -> None:
    assert measure.split_windows(1.0, 2.0, config.load_media().measure) == [(1.0, 2.0)]


def test_five_seconds_makes_two_windows_of_two_and_a_half() -> None:
    windows = measure.split_windows(0.0, 5.0, config.load_media().measure)

    assert windows == [(0.0, 2.5), (2.5, 5.0)]
