"""`make` (docs/EDITOR.md §3, §6): plan, render, judge, revise once, ship; fake model and media."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.core.errors import CostCapReached
from reel_studio.editor import make, prompt
from tests.fakes.claude import FakeClaude, response, text
from tests.fakes.clock import FrozenClock
from tests.fakes.media import FakeMedia, critic_turn, edl_turn


def _make(
    tmp_path: Path, script: list[Any], cfg: config.Config | None = None
) -> tuple[make.Made, FakeClaude, FakeMedia]:
    fake, media = FakeClaude(script), FakeMedia()
    folder = tmp_path / "creami"
    folder.mkdir()
    order = prompt.OrderSettings("montage", 30, "en", False)
    request = make.Request(folder=folder, out=tmp_path / "out" / "creami", order=order)
    ports = make.Ports(claude=fake, clock=FrozenClock(datetime(2026, 10, 10, tzinfo=UTC)))
    steps = make.Steps(media.prepare, media.render)
    made = make.make(request, ports, steps, cfg if cfg is not None else config.load())
    return made, fake, media


def test_a_passing_first_render_ships_with_its_record(tmp_path: Path) -> None:
    made, fake, _ = _make(tmp_path, [edl_turn("e1"), critic_turn(5)])

    assert (made.renders, made.final.passed) == (1, True)
    assert (made.out / "text.mp4").read_bytes() == b"render 1"
    assert (made.out / "clean.mp4").is_file() and (made.out / "edl.json").is_file()
    record = json.loads((made.out / "result.json").read_text())
    assert record["critic"]["passed"] is True and record["critic"]["total"] == 29
    assert record["cost_usd"] == str(made.cost) and made.cost > 0
    assert record["edl_warnings"] == made.warnings and made.warnings  # 4 s is short for a dessert
    calls = [json.loads(x)["call"] for x in (made.out / "requests.jsonl").read_text().splitlines()]
    assert calls == ["editor", "critic"]
    assert fake.requests[1]["model"] == config.load().limits.editor.critic_model


def test_a_failed_render_goes_back_to_the_same_conversation_once(tmp_path: Path) -> None:
    script = [edl_turn("e1"), critic_turn(3), edl_turn("e2"), critic_turn(5)]
    made, fake, _ = _make(tmp_path, script)

    assert (made.renders, made.final.passed) == (2, True)
    assert (made.out / "text.mp4").read_bytes() == b"render 2"
    revise = fake.requests[2]
    assert revise["system"] == fake.requests[0]["system"]  # cached prefix kept (D34)
    assert revise["messages"][: len(fake.requests[0]["messages"])] == fake.requests[0]["messages"]
    assert "open on c01 5s" in revise["messages"][-1]["content"][-1]["text"]


def test_two_failed_renders_ship_the_better_and_name_the_weakness(tmp_path: Path) -> None:
    script = [edl_turn("e1"), critic_turn(3), edl_turn("e2"), critic_turn(2)]
    made, _, _ = _make(tmp_path, script)

    assert (made.renders, made.final.passed) == (2, False)
    assert (made.out / "text.mp4").read_bytes() == b"render 1"
    record = json.loads((made.out / "result.json").read_text())
    assert "hook 3 < 4" in record["critic"]["weakness"]


def test_the_cost_cap_stops_the_order_before_the_call(tmp_path: Path) -> None:
    cfg = config.load()
    editor = cfg.limits.editor.model_copy(update={"cost_cap_usd": Decimal(0)})
    capped = cfg.model_copy(update={"limits": cfg.limits.model_copy(update={"editor": editor})})

    with pytest.raises(CostCapReached):
        _make(tmp_path, [edl_turn("e1")], capped)


def test_every_renders_review_is_kept(tmp_path: Path) -> None:
    script = [edl_turn("e1"), critic_turn(3), edl_turn("e2"), critic_turn(2)]
    made, _, _ = _make(tmp_path, script)

    record = json.loads((made.out / "result.json").read_text())

    assert [r["render"] for r in record["reviews"]] == [1, 2]
    assert [r["scores"]["hook"] for r in record["reviews"]] == [3, 2]
    assert record["reviews"][1]["total"] == 26 and record["reviews"][1]["passed"] is False


def test_a_render_the_critic_could_not_judge_still_ships(tmp_path: Path) -> None:
    made, _, _ = _make(tmp_path, [edl_turn("e1"), response([text("No.")], "refusal")])

    record = json.loads((made.out / "result.json").read_text())

    assert (made.out / "text.mp4").read_bytes() == b"render 1"
    assert made.final.review is None and not made.final.passed
    assert record["critic"]["total"] is None and "model_refusal" in record["critic"]["weakness"]
