"""Fake media steps for `make` (prepare, render, QA) and scripted model turns that drive them.

FakeMedia writes the files the real steps write (text.mp4, clean.mp4, qa.json, the three review
sheets in the shared review/ folder), so the code under test handles them exactly as in a run.
"""

from pathlib import Path
from typing import Any

from PIL import Image

from reel_studio.editor import make
from reel_studio.editor.media import qa, render
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.media.shots import Clip, Shots
from tests.fakes.claude import response, tool_use

CATEGORIES = ("hook", "retention", "story", "peak", "craft", "share", "colour")
EDL = {
    "style": "montage",
    "versions": [
        {
            "name": "A",
            "segments": [
                {"clip": "c01", "in": 0, "out": 2, "role": "hook"},
                {"clip": "c01", "in": 5, "out": 7, "role": "payoff"},
            ],
        }
    ],
}


def review(hook: int) -> dict[str, Any]:  # Any: review JSON
    review: dict[str, Any] = {c: {"score": 4, "evidence": "hook 0.50s"} for c in CATEGORIES}
    review["hook"] = {"score": hook, "evidence": "hook 0.00s"}
    major = (
        [] if hook >= 4 else [{"where": "hook 0.00s", "problem": "soft", "fix": "open on c01 5s"}]
    )
    review.update(major=major, minor=[], works=["the payoff"], verdict="ready to post")
    return review


def shots(work: Path) -> Shots:
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
        median_sharpness=100.0,
    )
    sheet = work / "sheets" / "overview_01.jpg"
    sheet.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 40)).save(sheet)
    return Shots(name="t", clips=[clip], windows=[], sheets=[str(sheet)], total_raw_seconds=10.0)


class FakeMedia:
    """Stands in for prepare, render and QA: writes the files they would write."""

    def __init__(self) -> None:
        self.rendered: list[Edl] = []

    def prepare(self, folder: Path, work: Path) -> Shots:
        return shots(work)

    def render(self, out_dir: Path, shots: Shots, edl: Edl) -> make.Rendered:
        self.rendered.append(edl)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in (render.TEXT, render.CLEAN):
            (out_dir / name).write_bytes(f"render {len(self.rendered)}".encode())
        sheets = []
        for name in ("hook", "cuts", "overview"):
            sheets.append(out_dir.parent.parent / "review" / f"{name}.jpg")  # shared, as in qa.run
            sheets[-1].parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (60, 40), (len(self.rendered), 0, 0)).save(sheets[-1])
        checks = dict.fromkeys(qa.HardChecks.model_fields, True)
        result = qa.QaResult(
            hard_checks=qa.HardChecks(**checks),
            lines=["PASS  spec"],
            audio=qa.AudioResult(lufs=-14.0, black=[], freeze=[]),
            cuts=[],
            segments=[],
            median_motion=0.0,
            median_sharpness=0.0,
            loop=None,
            sheets=[str(s) for s in sheets],
        )
        timeline = render.Timeline(
            files={}, duration=4.0, planned_duration=4.0, segments=[], text=[]
        )
        (out_dir / qa.QA_JSON).write_text(result.model_dump_json(), encoding="utf-8")
        return make.Rendered(out_dir, timeline, result)


def edl_turn(block_id: str) -> dict[str, Any]:  # Any: response JSON
    return response([tool_use(block_id, "write_edl", EDL)], "tool_use")


def critic_turn(hook: int) -> dict[str, Any]:  # Any: response JSON
    return response([tool_use("r", "submit_review", review(hook))], "tool_use")
