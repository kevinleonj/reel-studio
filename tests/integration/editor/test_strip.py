"""Filmstrips for choosing exact in/out points (kit strip.py), capped at 2000 px (F08)."""

from pathlib import Path

import pytest
from PIL import Image

from reel_studio.core import config
from reel_studio.editor.media import prepare, strip
from tests.fixtures import make_clips

MAX_SIDE = config.load().limits.sheets.max_image_side_px


def _proxy(prepared: tuple[Path, list[prepare.Proxy]], name: str) -> prepare.Proxy:
    return next(p for p in prepared[1] if p.source == name)


def test_whole_long_take_strip_fits_2000_px(
    prepared: tuple[Path, list[prepare.Proxy]], tmp_path: Path
) -> None:
    work, _ = prepared
    proxy = _proxy(prepared, make_clips.LONG_TAKE)
    limits = config.load().limits.sheets

    request = strip.Request(proxy, None, None)
    path = strip.strip(work, request, tmp_path, config.load_media(), limits.max_image_side_px)

    with Image.open(path) as image:
        assert max(image.size) <= limits.max_image_side_px
    assert path.name == f"{proxy.id}_0.0-{proxy.duration:.1f}.jpg"


def test_end_past_the_clip_is_clamped(
    prepared: tuple[Path, list[prepare.Proxy]], tmp_path: Path
) -> None:
    work, _ = prepared
    proxy = _proxy(prepared, make_clips.SIXTY_FPS)

    request = strip.Request(proxy, 2.0, 99.0)
    path = strip.strip(work, request, tmp_path, config.load_media(), MAX_SIDE)

    assert path.name == f"{proxy.id}_2.0-{proxy.duration:.1f}.jpg"


def test_empty_range_is_refused(prepared: tuple[Path, list[prepare.Proxy]], tmp_path: Path) -> None:
    work, _ = prepared
    proxy = _proxy(prepared, make_clips.SIXTY_FPS)

    with pytest.raises(ValueError, match="Range must be inside"):
        strip.strip(work, strip.Request(proxy, 3.0, 3.0), tmp_path, config.load_media(), MAX_SIDE)
