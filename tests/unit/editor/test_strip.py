"""How many frames a strip shows (kit strip.py:40-41)."""

import pytest

from reel_studio.core import config
from reel_studio.editor.media import strip


@pytest.mark.parametrize(
    ("start", "end", "count"),
    [(0.0, 0.5, 6), (0.0, 3.0, 12), (0.0, 90.0, 30)],
)
def test_frame_count_is_one_per_quarter_second_between_6_and_30(
    start: float, end: float, count: int
) -> None:
    times = strip.frame_times(start, end, config.load_media().strip)

    assert len(times) == count
    assert times[0] == start
    assert times[-1] == pytest.approx(end - config.load_media().strip.end_inset_s)
