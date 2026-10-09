"""LUTs and the looks preview on the real proxies (kit grade.py), preview within 2000 px (F08)."""

from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.editor.media import grade, measure, prepare
from reel_studio.editor.media.shots import Clip, Shots


@pytest.fixture(scope="module")
def shots(prepared: tuple[Path, list[prepare.Proxy]]) -> Shots:
    work, proxies = prepared
    media = config.load_media()
    clips, windows = [], []
    for proxy in proxies:
        measured = measure.measure_clip(work, proxy, media)
        clips.append(Clip.of(proxy, measured.color_stats, measured.median_sharpness))
        windows += measured.windows
    return Shots(name="fixtures", clips=clips, windows=windows, sheets=[], total_raw_seconds=0.0)


def test_every_clip_gets_a_cube(shots: Shots, clips_dir: Path, tmp_path: Path) -> None:
    media = config.load_media()
    ref = grade.reference_of(shots, clips_dir, media)
    choice = grade.Choice("reference", 0.6, 0.6)

    luts = grade.build_luts(shots, choice, ref, tmp_path, media.grade)

    assert set(luts) == {c.id for c in shots.clips}
    assert ref.ref is not None  # the style photo in the fixture folder


def test_preview_fits_2000_px(
    prepared: tuple[Path, list[prepare.Proxy]], shots: Shots, clips_dir: Path
) -> None:
    work, _ = prepared
    media = config.load_media()
    ref = grade.reference_of(shots, clips_dir, media)

    image = grade.preview(work, shots, grade.Choice("natural", 0.6, 0.6), ref, media)

    assert max(image.size) <= config.load().limits.sheets.max_image_side_px
    assert image.size[0] > 0 and image.size[1] > 0
