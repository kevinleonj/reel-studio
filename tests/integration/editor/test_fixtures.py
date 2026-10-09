"""The synthetic clips stand in for an iPhone folder (kit selftest.py:6-7, STEP-02 task 1)."""

from pathlib import Path

from tests.fixtures import make_clips
from tests.integration.editor.conftest import probe


def _video(data: dict[str, object]) -> dict[str, object]:
    streams = data["streams"]
    assert isinstance(streams, list)
    return next(s for s in streams if s["codec_type"] == "video")


def _has_audio(data: dict[str, object]) -> bool:
    streams = data["streams"]
    assert isinstance(streams, list)
    return any(s["codec_type"] == "audio" for s in streams)


def test_folder_holds_five_media_files_and_a_style_photo(clips_dir: Path) -> None:
    names = sorted(p.name for p in clips_dir.iterdir())

    assert names == sorted(make_clips.NAMES)


def test_hdr_clip_is_hevc_10_bit_hlg_with_rotation(
    clips_dir: Path, tools: make_clips.Tools
) -> None:
    video = _video(probe(tools, clips_dir / make_clips.HDR))

    assert video["codec_name"] == "hevc"
    assert video["pix_fmt"] == "yuv420p10le"
    assert video["color_transfer"] == "arib-std-b67"
    side = video.get("side_data_list")
    assert isinstance(side, list)
    assert any(abs(float(d.get("rotation", 0))) == 90 for d in side)


def test_sixty_fps_clip_has_audio(clips_dir: Path, tools: make_clips.Tools) -> None:
    data = probe(tools, clips_dir / make_clips.SIXTY_FPS)

    assert _video(data)["avg_frame_rate"] == "60/1"
    assert _has_audio(data)


def test_landscape_clip_has_no_audio(clips_dir: Path, tools: make_clips.Tools) -> None:
    data = probe(tools, clips_dir / make_clips.LANDSCAPE)
    video = _video(data)

    assert video["width"] == 1920 and video["height"] == 1080
    assert not _has_audio(data)


def test_long_take_runs_ninety_seconds(clips_dir: Path, tools: make_clips.Tools) -> None:
    data = probe(tools, clips_dir / make_clips.LONG_TAKE)
    fmt = data["format"]
    assert isinstance(fmt, dict)

    assert abs(float(fmt["duration"]) - make_clips.LONG_TAKE_S) < 0.5
    assert _has_audio(data)
