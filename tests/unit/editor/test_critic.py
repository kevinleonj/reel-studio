"""The critic (docs/EDITOR.md §6, D36): gates in code, at most 2 renders, ship the higher total."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from reel_studio.core import config
from reel_studio.core.errors import ModelRefusal
from reel_studio.editor import critic, loop, meter
from tests.fakes.claude import FakeClaude, response, text, tool_use
from tests.fakes.clock import FrozenClock

TOOL = "submit_review"
CATEGORIES = ("hook", "retention", "story", "peak", "craft", "share", "colour")


def _scores(**override: int) -> dict[str, Any]:  # Any: review JSON
    review: dict[str, Any] = {c: {"score": 4, "evidence": f"{c} 0.50s"} for c in CATEGORIES}
    for name, value in override.items():
        review[name] = {"score": value, "evidence": f"{name} tile"}
    review.update(major=[], minor=[], works=["clean cuts"], verdict="ready to post")
    return review


def _review(**override: int) -> critic.Review:
    return critic.Review.model_validate(_scores(**override))


GATES = config.load().limits.gates


@pytest.mark.parametrize(
    ("override", "ok"),
    [
        ({}, True),
        ({"hook": 3}, False),
        ({"craft": 2}, False),
        ({"retention": 3, "story": 3, "share": 3}, False),
        ({"hook": 5, "story": 3}, True),
    ],
)
def test_gates(override: dict[str, int], ok: bool) -> None:
    assert critic.passes(_review(**override), GATES)[0] is ok


def test_a_failed_gate_is_named() -> None:
    ok, why = critic.passes(_review(hook=3), GATES)

    assert not ok and "hook 3 < 4" in why


class _Cycle:
    def __init__(self, reviews: list[critic.Review]) -> None:
        self.reviews, self.renders = reviews, 0
        self.feedback: list[str | None] = []

    def plan(self, feedback: str | None) -> str:
        self.feedback.append(feedback)
        return f"edl{len(self.feedback)}"

    def render(self, edl: str, number: int) -> str:
        self.renders += 1
        return f"render{number}-{edl}"

    def judge(self, rendered: str) -> critic.Review:
        return self.reviews.pop(0)


def _cycle(reviews: list[critic.Review]) -> tuple[critic.Final[str], _Cycle]:
    c = _Cycle(reviews)
    final = critic.review_cycle(
        c.plan, c.render, c.judge, GATES, config.load().limits.editor.max_renders
    )
    return final, c


def test_pass_at_render_1_stops() -> None:
    final, c = _cycle([_review()])

    assert (final.render, final.passed, c.renders) == ("render1-edl1", True, 1)
    assert c.feedback == [None]


def test_fail_then_pass_ships_the_second_render_and_sends_the_issues_back() -> None:
    first = _scores(hook=3)
    first["major"] = [
        {"where": "hook 0.00s", "problem": "soft first frame", "fix": "open on c04 at 2.1s"}
    ]
    final, c = _cycle([critic.Review.model_validate(first), _review(hook=5)])

    assert (final.render, final.passed, c.renders) == ("render2-edl2", True, 2)
    assert c.feedback[1] is not None and "open on c04 at 2.1s" in c.feedback[1]


def test_fail_twice_ships_the_higher_total_with_the_weakness_named() -> None:
    better, worse = _review(hook=3, story=5), _review(hook=2)
    final, c = _cycle([better, worse])

    assert final.render == "render1-edl1" and not final.passed
    assert final.weakness is not None and "hook 3 < 4" in final.weakness
    assert c.renders == 2


def test_critic_call_is_fresh_forces_submit_review_and_sends_three_sheets(tmp_path: Path) -> None:
    sheets = []
    for name in ("hook", "cuts", "overview"):
        sheets.append(tmp_path / f"{name}.jpg")
        Image.new("RGB", (600, 400), (40, 40, 40)).save(sheets[-1])
    fake = FakeClaude([response([tool_use("r", "submit_review", _scores())], "tool_use")])
    limits = config.load().limits
    session = loop.Session(
        claude=fake,
        meter=meter.Meter(config.load().prices, Decimal("5")),
        clock=FrozenClock(datetime(2026, 10, 10, tzinfo=UTC)),
        log=tmp_path / "requests.jsonl",
        editor=limits.editor,
        call="critic",
    )
    material = critic.Material(
        sheets=sheets,
        qa_lines=["PASS  text.mp4 ..."],
        timeline="seg 0 hook 0.0-1.5s",
        order="style montage, 30 s, text English, voice off",
    )

    quality = config.load_media().contact_sheet.jpeg_quality
    review = critic.critique(
        session, "CRITIC SYSTEM", material, limits.sheets.max_image_side_px, quality
    )

    request = fake.requests[0]
    assert review.total == 28
    assert request["model"] == limits.editor.critic_model
    assert request["tool_choice"] == {"type": "tool", "name": "submit_review"}
    assert len(request["messages"]) == 1  # never the editor's conversation
    blocks = request["messages"][0]["content"]
    assert sum(1 for b in blocks if b["type"] == "image") == 3


def _critique(tmp_path: Path, reply: dict[str, Any]) -> critic.Review:  # Any: response JSON
    sheet = tmp_path / "hook.jpg"
    Image.new("RGB", (60, 40)).save(sheet)
    limits = config.load().limits
    session = loop.Session(
        claude=FakeClaude([reply]),
        meter=meter.Meter(config.load().prices, Decimal("5")),
        clock=FrozenClock(datetime(2026, 10, 10, tzinfo=UTC)),
        log=tmp_path / "requests.jsonl",
        editor=limits.editor,
        call="critic",
    )
    material = critic.Material(sheets=[sheet], qa_lines=[], timeline="", order="")
    quality = config.load_media().contact_sheet.jpeg_quality
    return critic.critique(session, "S", material, limits.sheets.max_image_side_px, quality)


def test_a_reply_without_a_review_is_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(ModelRefusal, match="refusal"):
        _critique(tmp_path, response([text("No.")], "refusal"))


def test_a_score_outside_the_scale_is_rejected(tmp_path: Path) -> None:
    bad = _scores(hook=7)

    with pytest.raises(ModelRefusal, match="invalid"):
        _critique(tmp_path, response([tool_use("r", TOOL, bad)], "tool_use"))


def test_the_review_tool_is_strict_and_carries_no_bounds() -> None:
    definition = critic.tool_definition()
    schema = json.dumps(definition["input_schema"])

    assert definition["strict"] is True
    assert "maximum" not in schema and "minimum" not in schema
    assert definition["input_schema"]["additionalProperties"] is False
