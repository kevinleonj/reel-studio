"""Contact sheets from the real proxies (D38, F08)."""

from collections import Counter
from pathlib import Path

from PIL import Image

from reel_studio.core import config
from reel_studio.editor.media import measure, prepare, sheets


def test_every_clip_gets_two_to_six_tiles_on_full_size_sheets(
    prepared: tuple[Path, list[prepare.Proxy]], tmp_path: Path
) -> None:
    work, proxies = prepared
    limits, media = config.load().limits.sheets, config.load_media()
    clips = [
        (p, measure.detect_cuts(work / p.path, media.measure) if p.kind == "video" else [])
        for p in proxies
    ]

    paths, legend = sheets.build(work, clips, tmp_path, limits, media)

    per_clip = Counter(t.clip for t in legend)
    assert set(per_clip) == {p.id for p in proxies}
    assert all(
        limits.frames_per_clip_min <= n <= limits.frames_per_clip_max for n in per_clip.values()
    )
    for path in paths:
        with Image.open(path) as image:
            assert image.size == (1536, 864)
            assert max(image.size) <= limits.max_image_side_px
    assert (tmp_path / sheets.LEGEND).exists()
