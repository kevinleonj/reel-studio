"""`reel render` end to end: outputs in --out, the input folder byte-identical (D02)."""

import hashlib
import json
from pathlib import Path

from reel_studio.cli import reel
from reel_studio.editor.media import qa, render
from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings
from tests.fixtures import make_clips

BASIC = Path(__file__).resolve().parents[2] / "fixtures" / "edl" / "basic.json"


def _tree(folder: Path) -> dict[str, str]:
    """Every file under `folder` by relative path, so an added or removed file also shows."""
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def test_render_writes_outputs_and_leaves_the_input_identical(
    clips_dir: Path, tools: make_clips.Tools, tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = make_settings(
        EditorSettings, ffmpeg_path=str(tools.ffmpeg), ffprobe_path=str(tools.ffprobe)
    )
    assert isinstance(settings, EditorSettings)
    before = _tree(clips_dir)
    out = tmp_path / "Sofia's reel: v2"  # a quote and a colon once broke the LUT filter

    code = reel.main(["render", "--edl", str(BASIC), str(clips_dir), "--out", str(out)], settings)

    assert code == 0
    assert _tree(clips_dir) == before
    assert (out / render.TEXT).exists() and (out / render.CLEAN).exists()
    checks = json.loads((out / qa.QA_JSON).read_text(encoding="utf-8"))["hard_checks"]
    assert checks and all(v is True for v in checks.values())


def test_edl_with_errors_exits_2_without_rendering(
    clips_dir: Path, tools: make_clips.Tools, tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = make_settings(
        EditorSettings, ffmpeg_path=str(tools.ffmpeg), ffprobe_path=str(tools.ffprobe)
    )
    assert isinstance(settings, EditorSettings)
    bad = json.loads(BASIC.read_text(encoding="utf-8"))
    bad["audio"]["music"] = "song.mp3"
    edl = tmp_path / "bad.json"
    edl.write_text(json.dumps(bad), encoding="utf-8")
    out = tmp_path / "out"

    code = reel.main(["render", "--edl", str(edl), str(clips_dir), "--out", str(out)], settings)

    assert code == 2
    assert not (out / render.TEXT).exists()
