"""The critic (docs/EDITOR.md §6, D36): gates in code, at most 2 renders, ship the higher total."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from reel_studio.core import config
from reel_studio.core.errors import CostCapReached, ModelRefusal
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


def test_critic_call_is_fresh_with_auto_choice_and_three_sheets(tmp_path: Path) -> None:
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
    assert request["tool_choice"] == {"type": "auto"}  # any/tool are a 400 on Sonnet 5.5 (F10)
    assert len(request["messages"]) == 1  # never the editor's conversation
    blocks = request["messages"][0]["content"]
    assert sum(1 for b in blocks if b["type"] == "image") == 3


def _critique(tmp_path: Path, *replies: dict[str, Any]) -> tuple[critic.Review, FakeClaude]:
    sheet, fake = tmp_path / "hook.jpg", FakeClaude(list(replies))
    Image.new("RGB", (60, 40)).save(sheet)
    limits = config.load().limits
    session = loop.Session(
        claude=fake,
        meter=meter.Meter(config.load().prices, Decimal("5")),
        clock=FrozenClock(datetime(2026, 10, 10, tzinfo=UTC)),
        log=tmp_path / "requests.jsonl",
        editor=limits.editor,
        call="critic",
    )
    material = critic.Material(sheets=[sheet], qa_lines=[], timeline="", order="")
    quality = config.load_media().contact_sheet.jpeg_quality
    side = limits.sheets.max_image_side_px
    return critic.critique(session, "S", material, side, quality), fake


def test_a_refusal_fails_at_once(tmp_path: Path) -> None:
    with pytest.raises(ModelRefusal, match="refusal"):
        _critique(tmp_path, response([text("No.")], "refusal"))


def test_a_text_reply_gets_one_nudge_then_the_review_counts(tmp_path: Path) -> None:
    review, fake = _critique(
        tmp_path,
        response([text("Looks good.")], "end_turn"),
        response([tool_use("r", TOOL, _scores())], "tool_use"),
    )

    assert review.total == 28
    assert fake.requests[1]["messages"][-1] == {"role": "user", "content": critic.NUDGE}


def test_two_text_replies_are_a_refusal(tmp_path: Path) -> None:
    words = response([text("Looks good.")], "end_turn")

    with pytest.raises(ModelRefusal, match="no review"):
        _critique(tmp_path, words, words)


def test_an_invalid_review_gets_its_problems_back_once(tmp_path: Path) -> None:
    bad = response([tool_use("r", TOOL, _scores(hook=7))], "tool_use")
    good = response([tool_use("r2", TOOL, _scores())], "tool_use")

    review, fake = _critique(tmp_path, bad, good)

    assert review.total == 28
    answer = fake.requests[1]["messages"][-1]
    assert answer["role"] == "user"
    result = answer["content"][0]
    assert (result["type"], result["tool_use_id"], result["is_error"]) == ("tool_result", "r", True)
    assert "hook" in result["content"]


def test_two_invalid_reviews_are_a_refusal(tmp_path: Path) -> None:
    bad = response([tool_use("r", TOOL, _scores(hook=7))], "tool_use")

    with pytest.raises(ModelRefusal, match="invalid"):
        _critique(tmp_path, bad, bad)


def test_an_empty_reply_is_not_sent_back(tmp_path: Path) -> None:
    empty = response([], "end_turn")

    _, fake = _critique(tmp_path, empty, response([tool_use("r", TOOL, _scores())], "tool_use"))

    messages = fake.requests[1]["messages"]
    assert all(m["content"] for m in messages)
    assert [m["role"] for m in messages] == ["user"]
    assert messages[0]["content"][-1] == {"type": "text", "text": critic.NUDGE}


class _FailingRevision(_Cycle):
    def plan(self, feedback: str | None) -> str:
        if feedback is not None:
            raise CostCapReached("spent $4.90 + worst case $0.30 > cap $5")
        return super().plan(feedback)


def test_an_error_while_revising_ships_the_first_render_and_names_it() -> None:
    c = _FailingRevision([_review(hook=3)])

    final = critic.review_cycle(
        c.plan, c.render, c.judge, GATES, config.load().limits.editor.max_renders
    )

    assert final.render == "render1-edl1" and not final.passed
    assert final.weakness is not None
    assert "hook 3 < 4" in final.weakness and "cost_cap" in final.weakness


def test_the_review_tool_is_strict_and_carries_no_bounds() -> None:
    definition = critic.tool_definition()
    schema = json.dumps(definition["input_schema"])

    assert definition["strict"] is True
    assert "maximum" not in schema and "minimum" not in schema
    assert definition["input_schema"]["additionalProperties"] is False
