"""Render's pure parts: speed chains, crop, text timing; music refused before any ffmpeg call."""

from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.core.errors import RenderError
from reel_studio.editor.media import render, tools
from reel_studio.editor.media.edl_models import Edl, Framing, Segment, Version
from reel_studio.editor.media.shots import Clip, Shots


def _seg(**fields: object) -> Segment:
    return Segment.model_validate({"clip": "c01", "in": 0.0, "out": 2.0, **fields})


def test_eight_times_speed_is_three_atempo_stages() -> None:
    chain = render.atempo_chain(8.0, config.load_media().render.segment)

    assert chain == "atempo=2.0,atempo=2.0,atempo=2.0000"


def test_quarter_speed_is_two_atempo_stages() -> None:
    chain = render.atempo_chain(0.25, config.load_media().render.segment)

    assert chain == "atempo=0.5,atempo=0.5000"


def test_crop_fills_the_frame_at_the_focus_point() -> None:
    clip = _clip(3414, 1920)
    frame = render.resolve(_seg(focus_x=0.2), Framing(), config.load_media())

    assert render.crop_filter(clip, frame) == (
        "crop=1080:1920:466:0,scale=1080:1920:flags=lanczos,setsar=1"
    )


def test_zoom_and_half_turn() -> None:
    frame = render.resolve(_seg(zoom=2.0, rotate=180), Framing(), config.load_media())

    out = render.crop_filter(_clip(1080, 1920), frame)

    assert out.startswith("crop=540:960:270:480,")
    assert out.endswith(",hflip,vflip")


def test_step_label_waits_for_the_hook_in_the_same_position() -> None:
    # Hook "Hook" shows 0-2.5 s at the top. "First" (0-2 s, top) would start after the hook
    # and end before it starts, so it is dropped; "Second" (2-4 s) starts when the hook ends.
    version = Version(
        name="A",
        hook_text="Hook",
        segments=[_seg(text="First", text_position="top"), _seg(text="Second")],
    )

    events, _, total = render.text_events(version, config.load_media())

    assert total == pytest.approx(4.0)
    assert [(e.text, e.start, e.end) for e in events] == [("Hook", 0.0, 2.5), ("Second", 2.5, 4.0)]


def test_label_in_another_position_overlaps_the_hook() -> None:
    version = Version(
        name="A", hook_text="Hook", segments=[_seg(text="Low label", text_position="low")]
    )

    events, _, _ = render.text_events(version, config.load_media())

    assert [(e.text, e.start, e.end) for e in events] == [
        ("Hook", 0.0, 2.0),
        ("Low label", 0.0, 2.0),
    ]


def test_music_is_refused_before_ffmpeg_runs(tmp_path: Path) -> None:
    edl = Edl.model_validate(
        {
            "versions": [{"name": "A", "segments": [{"clip": "c01", "in": 0, "out": 1}]}],
            "audio": {"music": "song.mp3"},
        }
    )
    media = config.load_media()
    missing = tmp_path / "no-ffmpeg"  # any ffmpeg call would fail with FileNotFoundError instead
    ffmpeg = tools.Ffmpeg(missing, missing, media.tools)
    job = render.Job(work=tmp_path, input_dir=None, out_dir=tmp_path, ffmpeg=ffmpeg, media=media)
    shots = Shots(name="t", clips=[_clip(1080, 1920)], windows=[], sheets=[], total_raw_seconds=1.0)

    with pytest.raises(RenderError, match="music"):
        render.render(job, shots, edl)


def _clip(width: int, height: int) -> Clip:
    return Clip(
        id="c01",
        source="a.mov",
        proxy="clips/c01.mp4",
        duration=10.0,
        orientation="portrait",
        proxy_w=width,
        proxy_h=height,
        proxy_fps=30,
        color="sdr",
        kind="video",
        color_stats=None,
        median_sharpness=1.0,
    )
