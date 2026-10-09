"""ffmpeg/ffprobe runner: errors keep the stderr tail, probes swap size for rotated clips."""

import io
import json
import logging
import sys
from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.core.errors import RenderError
from reel_studio.core.logging import configure
from reel_studio.editor.media import tools

STDERR_LINES = 40


def _runner() -> tools.Ffmpeg:
    # The Python interpreter stands in for ffmpeg: no video needed to test the error path.
    python = Path(sys.executable)
    return tools.Ffmpeg(python, python, config.load_media().tools)


def test_failed_run_raises_render_error_with_the_last_15_stderr_lines() -> None:
    script = (
        f"import sys; sys.stderr.write(chr(10).join(map(str, range({STDERR_LINES})))); sys.exit(3)"
    )

    with pytest.raises(RenderError) as caught:
        _runner().run(["-c", script], "Normalising IMG_0001.MOV")

    message = str(caught.value)
    assert "Normalising IMG_0001.MOV failed (exit 3)" in message
    assert "\n25\n" in message and message.endswith("39")
    assert "\n24\n" not in message


def test_successful_run_returns_stderr() -> None:
    out = _runner().run(["-c", "import sys; sys.stderr.write('ok')"], "noop")

    assert out == "ok"


def test_every_run_logs_one_json_line_with_latency() -> None:
    stream = io.StringIO()
    configure(logging.INFO, stream)

    _runner().run(["-c", "pass"], "noop")

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(lines) == 1
    assert lines[0]["event"] == "ffmpeg"
    assert lines[0]["outcome"] == "ok"
    assert isinstance(lines[0]["latency_ms"], int)


ROTATED = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "r_frame_rate": "30/1",
            "duration": "4.0",
            "pix_fmt": "yuv420p10le",
            "color_transfer": "arib-std-b67",
            "side_data_list": [{"rotation": -90}],
        },
        {"codec_type": "audio"},
    ],
    "format": {"duration": "4.0", "tags": {"creation_time": "2026-10-09T10:00:00Z"}},
}


def test_probe_swaps_width_and_height_for_a_quarter_turn() -> None:
    info = tools.parse_probe(ROTATED, "IMG_0001.MOV")

    assert (info.width, info.height) == (1080, 1920)
    assert info.fps == pytest.approx(30.0)
    assert info.has_audio
    assert tools.is_hdr(info)


def test_probe_without_video_stream_fails() -> None:
    with pytest.raises(RenderError, match="no video stream"):
        tools.parse_probe({"streams": [{"codec_type": "audio"}], "format": {}}, "song.m4a")
