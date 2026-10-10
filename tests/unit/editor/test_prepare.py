"""prepare's pure parts: cover size, tonemap chain, capture order (kit prep.py:37-63)."""

from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.core.errors import MediaError
from reel_studio.editor.media import prepare
from reel_studio.editor.media.tools import Probe

CAP = config.load_media().prepare.max_pixels


def test_cover_size_fills_the_reel_frame_with_even_sides() -> None:
    assert prepare.cover_size(1920, 1080, CAP) == (3414, 1920)
    assert prepare.cover_size(1080, 1920, CAP) == (1080, 1920)
    assert prepare.cover_size(1200, 1600, CAP) == (1440, 1920)


def test_a_sliver_whose_cover_passes_the_pixel_cap_is_a_media_error() -> None:
    # 1 x 10000 would cover at 1080 x 10,800,000: 11.7 gigapixels, about 33 GiB as RGB.
    with pytest.raises(MediaError, match="pixels"):
        prepare.cover_size(1, 10000, CAP)


def test_tonemap_chain_uses_the_kit_curve_and_peak() -> None:
    chain = prepare.tonemap_chain("arib-std-b67", config.load_media().prepare.tonemap)

    assert chain.startswith("zscale=tin=arib-std-b67:pin=bt2020:min=bt2020nc:t=linear:npl=100,")
    assert "tonemap=tonemap=mobius:desat=0" in chain
    assert chain.endswith("zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def _probe(created: str | None) -> Probe:
    return Probe(1080, 1920, 30.0, 1.0, "h264", "yuv420p", None, None, None, True, created)


def test_capture_time_orders_before_file_name(tmp_path: Path) -> None:
    late, early = tmp_path / "a.mov", tmp_path / "b.mov"
    late.touch()
    early.touch()
    probes = {late: _probe("2026-10-09T12:00:00Z"), early: _probe("2026-10-09T08:00:00Z")}

    ordered = sorted([late, early], key=lambda p: prepare.sort_key(p, probes.get(p)))

    assert ordered == [early, late]


def test_footage_skips_briefs_hidden_files_and_style_photos(tmp_path: Path) -> None:
    for name in ("IMG_1.MOV", "brief.md", ".DS_Store", "IMG_2_vsco.jpg", "notes.txt", "IMG_3.jpeg"):
        (tmp_path / name).touch()

    names = [p.name for p in prepare.footage(tmp_path, config.load_media().grade.reference_words)]

    assert sorted(names) == ["IMG_1.MOV", "IMG_3.jpeg"]
