"""Scene cuts and measured windows on real proxies (kit prep.py:119-163, 276-290)."""

from pathlib import Path

from reel_studio.core import config
from reel_studio.editor.media import measure, prepare
from tests.fixtures import make_clips

CUT_TOLERANCE_S = 0.1


def _proxy(prepared: tuple[Path, list[prepare.Proxy]], name: str) -> tuple[Path, prepare.Proxy]:
    work, proxies = prepared
    return work, next(p for p in proxies if p.source == name)


def test_long_take_hard_cut_is_found(prepared: tuple[Path, list[prepare.Proxy]]) -> None:
    work, proxy = _proxy(prepared, make_clips.LONG_TAKE)

    scenes = measure.detect_cuts(work / proxy.path, config.load_media().measure)

    starts = [start for start, _ in scenes]
    assert any(abs(s - make_clips.CUT_AT_S) <= CUT_TOLERANCE_S for s in starts), scenes


def test_measured_clip_has_windows_and_colour_stats(
    prepared: tuple[Path, list[prepare.Proxy]],
) -> None:
    work, proxy = _proxy(prepared, make_clips.SIXTY_FPS)

    result = measure.measure_clip(work, proxy, config.load_media())

    assert result.windows
    assert all(w.clip == proxy.id and w.end > w.start for w in result.windows)
    assert result.color_stats is not None
    assert result.median_sharpness > 0


def test_photo_is_one_scene(prepared: tuple[Path, list[prepare.Proxy]]) -> None:
    work, proxy = _proxy(prepared, make_clips.PHOTO)

    result = measure.measure_clip(work, proxy, config.load_media())

    assert result.windows[0].start == 0.0
