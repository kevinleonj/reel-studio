"""Failure paths the phase B review found untested: they must fail closed and typed."""

from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.core.errors import RenderError
from reel_studio.editor.media import qa, render, render_filters, render_steps, tools
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.media.shots import Clip, Shots
from reel_studio.editor.media.tools import Probe
from tests.fakes.ffmpeg import FakeFfmpeg


def _shots() -> Shots:
    clip = Clip(
        id="c01",
        source="a.mov",
        proxy="clips/c01.mp4",
        duration=10.0,
        orientation="portrait",
        proxy_w=1080,
        proxy_h=1920,
        proxy_fps=30,
        color="sdr",
        kind="video",
        color_stats=None,
        median_sharpness=1.0,
    )
    return Shots(name="t", clips=[clip], windows=[], sheets=[], total_raw_seconds=10.0)


def _edl() -> Edl:
    return Edl.model_validate(
        {"versions": [{"name": "A", "segments": [{"clip": "c01", "in": 0, "out": 1}]}]}
    )


def test_missing_binary_is_a_render_error_not_a_crash(tmp_path: Path) -> None:
    missing = tmp_path / "ffmpeg"
    runner = tools.Ffmpeg(missing, missing, config.load_media().tools)

    with pytest.raises(RenderError, match="cannot start"):
        runner.run(["-version"], "check")


class _NoLoudness:
    def measure(self, args: list[str], what: str) -> str:
        return "Error opening input file x.mp4"


def test_a_failed_qa_measurement_fails_closed() -> None:
    with pytest.raises(RenderError, match="loudness"):
        qa.measure_audio(_NoLoudness(), Path("x.mp4"), config.load_media().qa)  # type: ignore[arg-type]


def test_wrong_size_output_fails_the_spec_check(tmp_path: Path) -> None:
    out = tmp_path / "text.mp4"
    out.write_bytes(b"x")
    small = Probe(720, 1280, 30.0, 10.0, "h264", "yuv420p", "bt709", None, None, True, None)
    fake: tools.Ffmpeg = FakeFfmpeg(probes={"text.mp4": small})  # type: ignore[assignment]
    job = render.Job(
        work=tmp_path, input_dir=None, out_dir=tmp_path, ffmpeg=fake, media=config.load_media()
    )
    lines = qa._Lines()

    form, fits = qa._spec(job, out, lines)

    assert (form, fits) == (False, True)
    assert lines.lines[0].startswith("FAIL")


def test_loud_peaks_use_gain_and_the_limiter_not_linear_loudnorm(tmp_path: Path) -> None:
    media = config.load_media()
    steps = render_steps.Steps(tmp_path, FakeFfmpeg(), _shots(), _edl(), media)  # type: ignore[arg-type]
    peaky = {
        "input_i": "-30.0",
        "input_tp": "-2.0",
        "input_lra": "5.0",
        "input_thresh": "-40.0",
        "target_offset": "0.0",
    }

    chain = steps.loud_filter(peaky)

    assert chain.startswith("volume=")
    assert f"alimiter=limit={media.render.loudness.limiter_limit}" in chain
    assert "linear=true" not in chain


def test_headroom_uses_linear_loudnorm(tmp_path: Path) -> None:
    steps = render_steps.Steps(tmp_path, FakeFfmpeg(), _shots(), _edl(), config.load_media())  # type: ignore[arg-type]
    room = {
        "input_i": "-20.0",
        "input_tp": "-12.0",
        "input_lra": "5.0",
        "input_thresh": "-30.0",
        "target_offset": "0.0",
    }

    assert "linear=true" in steps.loud_filter(room)


@pytest.mark.parametrize("bad", ["Sofia's reel", "a:b", "back\\slash"])
def test_lut_paths_that_would_break_the_filtergraph_are_refused(bad: str) -> None:
    with pytest.raises(RenderError, match="LUT path"):
        render_filters.grade_filter(None, Path("/work") / bad / "c01.cube", config.load_media())
