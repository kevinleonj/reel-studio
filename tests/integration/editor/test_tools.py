"""ffprobe on the real fixtures (kit common.py:105-147)."""

from pathlib import Path

from reel_studio.editor.media import tools
from tests.fixtures import make_clips


def test_rotated_hdr_clip_probes_as_portrait(clips_dir: Path, ffmpeg: tools.Ffmpeg) -> None:
    info = ffmpeg.probe(clips_dir / make_clips.HDR)

    assert (info.width, info.height) == (1080, 1920)
    assert tools.is_hdr(info)
    assert info.has_audio


def test_ffmpeg_has_zscale(ffmpeg: tools.Ffmpeg) -> None:
    assert ffmpeg.has_filter("zscale")
