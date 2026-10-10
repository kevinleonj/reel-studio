"""Contact sheets per D38: 4x4 tiles of 384x216 = 1536x864, legend, near-duplicates dropped."""

import numpy as np
import pytest

from reel_studio.core import config
from reel_studio.editor.media import sheets

PORTRAIT = (1920, 1080, 3)


def _frame(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, PORTRAIT, dtype=np.uint8)


def _shots(count: int, per_clip: int) -> list[sheets.Shot]:
    return [
        sheets.Shot(f"c{i // per_clip + 1:02d}", float(i % per_clip), _frame(i))
        for i in range(count)
    ]


def test_sheet_is_1536x864_with_16_tiles() -> None:
    limits = config.load().limits.sheets

    images, legend = sheets.draw(_shots(16, 4), limits, config.load_media())

    assert len(images) == 1
    assert images[0].size == (1536, 864)
    assert [t.tile for t in legend] == list(range(1, 17))


def test_seventeen_tiles_need_a_second_sheet() -> None:
    images, legend = sheets.draw(_shots(17, 4), config.load().limits.sheets, config.load_media())

    assert len(images) == 2
    assert (legend[-1].sheet, legend[-1].tile) == (2, 1)


def test_legend_maps_each_tile_to_its_clip_and_time() -> None:
    _, legend = sheets.draw(_shots(6, 3), config.load().limits.sheets, config.load_media())

    assert [(t.clip, t.t) for t in legend] == [
        ("c01", 0.0),
        ("c01", 1.0),
        ("c01", 2.0),
        ("c02", 0.0),
        ("c02", 1.0),
        ("c02", 2.0),
    ]


def test_scene_middles_are_the_frame_times() -> None:
    times = sheets.frame_times(
        [(0.0, 4.0), (4.0, 10.0), (10.0, 12.0)], 12.0, config.load().limits.sheets
    )

    assert times == [2.0, 7.0, 11.0]


def test_one_scene_still_gives_the_minimum_frames() -> None:
    limits = config.load().limits.sheets

    times = sheets.frame_times([(0.0, 8.0)], 8.0, limits)

    assert times == [2.0, 6.0]
    assert len(times) == limits.frames_per_clip_min


def test_many_scenes_are_thinned_to_the_maximum() -> None:
    limits = config.load().limits.sheets
    scenes = [(float(i), float(i + 1)) for i in range(20)]

    times = sheets.frame_times(scenes, 20.0, limits)

    assert len(times) == limits.frames_per_clip_max
    assert times[0] == 0.5 and times[-1] == 19.5


def test_near_duplicates_are_dropped_down_to_the_minimum() -> None:
    limits = config.load().limits.sheets
    same = _frame(1)
    candidates = [(0.0, same), (1.0, same.copy()), (2.0, _frame(2)), (3.0, same.copy())]

    kept = sheets.drop_near_duplicates(candidates, limits, config.load_media().qa)

    assert [t for t, _ in kept] == [0.0, 2.0]


def test_identical_frames_never_go_below_the_minimum() -> None:
    limits = config.load().limits.sheets
    same = _frame(1)

    kept = sheets.drop_near_duplicates(
        [(0.0, same), (1.0, same.copy())], limits, config.load_media().qa
    )

    assert len(kept) == limits.frames_per_clip_min


def test_no_frames_draw_no_sheets() -> None:
    images, legend = sheets.draw([], config.load().limits.sheets, config.load_media())

    assert images == [] and legend == []


@pytest.mark.parametrize("shape", [(1080, 1920, 3), (1920, 1080, 3)])
def test_tiles_fit_any_orientation(shape: tuple[int, int, int]) -> None:
    shot = sheets.Shot("c01", 0.0, np.zeros(shape, dtype=np.uint8))

    images, _ = sheets.draw([shot], config.load().limits.sheets, config.load_media())

    assert images[0].size == (1536, 864)
