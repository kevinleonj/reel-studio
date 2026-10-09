"""The whole pipeline on the fixtures: shots.json, then text.mp4 and clean.mp4 from basic.json."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from reel_studio.core import config, constants
from reel_studio.editor.media import edl, pipeline, render, tools
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.media.shots import Shots

BASIC = Path(__file__).resolve().parents[2] / "fixtures" / "edl" / "basic.json"
LUFS_TOLERANCE = 1.0  # the STEP-02 gate's tolerance
LUFS = re.compile(r"I:\s+(-?[\d.]+) LUFS")


def _hashes(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


@pytest.fixture(scope="module")
def rendered(
    clips_dir: Path, ffmpeg: tools.Ffmpeg, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Shots, render.Timeline, dict[str, str]]:
    before = _hashes(clips_dir)
    work, out = tmp_path_factory.mktemp("work"), tmp_path_factory.mktemp("out")
    media = config.load_media()
    shots = pipeline.build_shots(clips_dir, work, ffmpeg, media, config.load().limits.sheets)
    report = edl.validate(json.loads(BASIC.read_text(encoding="utf-8")), shots, media)
    assert report.errors == []
    assert isinstance(report.edl, Edl)
    job = render.Job(work=work, input_dir=clips_dir, out_dir=out, ffmpeg=ffmpeg, media=media)
    timeline = render.render(job, shots, report.edl)
    return out, shots, timeline, before


def test_shots_json_numbers_windows_and_lists_sheets(
    rendered: tuple[Path, Shots, render.Timeline, dict[str, str]],
) -> None:
    _, shots, _, _ = rendered

    assert [c.id for c in shots.clips] == ["c01", "c02", "c03", "c04", "c05"]
    assert shots.windows[0].id == "w001"
    assert shots.sheets


@pytest.mark.parametrize("name", [render.TEXT, render.CLEAN])
def test_output_matches_the_reel_spec(
    rendered: tuple[Path, Shots, render.Timeline, dict[str, str]], ffmpeg: tools.Ffmpeg, name: str
) -> None:
    out, _, timeline, _ = rendered
    info = ffmpeg.probe(out / name)

    assert (info.width, info.height) == (constants.OUT_W, constants.OUT_H)
    assert info.fps == pytest.approx(constants.OUT_FPS)
    assert info.codec == "h264"
    assert info.has_audio
    assert info.duration == pytest.approx(timeline.planned_duration, abs=0.2)


@pytest.mark.parametrize("name", [render.TEXT, render.CLEAN])
def test_loudness_is_minus_14_lufs(
    rendered: tuple[Path, Shots, render.Timeline, dict[str, str]], ffmpeg: tools.Ffmpeg, name: str
) -> None:
    out, _, _, _ = rendered
    args = [
        "-hide_banner",
        "-nostats",
        "-i",
        str(out / name),
        "-filter_complex",
        "[0:a]ebur128=peak=true[a]",
        "-map",
        "[a]",
        "-f",
        "null",
        "-",
    ]

    found = LUFS.findall(ffmpeg.measure(args, "loudness check"))

    assert found
    assert abs(float(found[-1]) - constants.TARGET_LUFS) <= LUFS_TOLERANCE


def test_input_folder_is_byte_identical(
    rendered: tuple[Path, Shots, render.Timeline, dict[str, str]], clips_dir: Path
) -> None:
    _, _, _, before = rendered

    assert _hashes(clips_dir) == before


def test_timeline_places_every_segment_and_text(
    rendered: tuple[Path, Shots, render.Timeline, dict[str, str]],
) -> None:
    _, _, timeline, _ = rendered

    assert len(timeline.segments) == 7
    assert [t["text"] for t in timeline.text] == [
        "Self test title card",
        "Slow motion",
        "Landscape crop",
        "Long take 4x",
    ]
    assert all(t["inside_safe_zone"] for t in timeline.text)
