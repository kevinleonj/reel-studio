"""The editor loop (docs/EDITOR.md §3) against a scripted fake Claude."""

import itertools
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.core.errors import CostCapReached, ModelRefusal, OutputTooLong
from reel_studio.editor import loop, meter, tools
from reel_studio.editor.media.shots import Clip, Shots
from tests.fakes.claude import FakeClaude, response, text, tool_use
from tests.fakes.clock import FrozenClock

GOOD_EDL = {
    "versions": [
        {
            "name": "A",
            "segments": [
                {"clip": "c01", "in": 0, "out": 2, "role": "hook"},
                {"clip": "c01", "in": 5, "out": 7, "role": "payoff"},
            ],
        }
    ]
}
BAD_EDL = {"versions": [{"name": "A", "segments": [{"clip": "c09", "in": 0, "out": 1}]}]}
NUDGE = "Call write_edl with the finished edit list."


def _box(tmp_path: Path) -> tools.Toolbox:
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
    shots = Shots(name="t", clips=[clip], windows=[], sheets=[], total_raw_seconds=10.0)
    ctx = tools.Context(
        work=tmp_path,
        input_dir=None,
        shots=shots,
        media=config.load_media(),
        limits=config.load().limits,
        order_style=None,
        voice=False,
    )
    return tools.Toolbox(ctx)


def _session(tmp_path: Path, fake: FakeClaude, cap: str = "5.0") -> loop.Session:
    return loop.Session(
        claude=fake,
        meter=meter.Meter(config.load().prices, Decimal(cap)),
        clock=FrozenClock(datetime(2026, 10, 10, 8, 0, tzinfo=UTC)),
        log=tmp_path / "requests.jsonl",
        editor=config.load().limits.editor,
    )


def _run(
    tmp_path: Path, script: list[Any], cap: str = "5.0"
) -> tuple[loop.Outcome, FakeClaude, tools.Toolbox]:
    fake, box = FakeClaude(script), _box(tmp_path)
    outcome = loop.run(_session(tmp_path, fake, cap), box, "SYSTEM PROMPT", "BRIEF")
    return outcome, fake, box


def test_a_valid_edit_list_ends_the_loop(tmp_path: Path) -> None:
    outcome, fake, _ = _run(
        tmp_path, [response([tool_use("t1", "write_edl", GOOD_EDL)], "tool_use")]
    )

    assert outcome.edl is not None and outcome.turns == 1
    assert len(fake.requests) == 1


def test_tools_system_choice_and_format_never_change(tmp_path: Path) -> None:
    script = [
        response([tool_use("t1", "read_sheet", {"sheet_id": "x"})], "tool_use"),
        response([tool_use("t2", "write_edl", BAD_EDL)], "tool_use"),
        response([tool_use("t3", "write_edl", GOOD_EDL)], "tool_use"),
    ]
    _, fake, _ = _run(tmp_path, script)

    fixed = {
        "model",
        "system",
        "tools",
        "tool_choice",
        "output_config",
        "cache_control",
        "max_tokens",
    }
    first = {k: fake.requests[0][k] for k in fixed}
    assert all({k: r[k] for k in fixed} == first for r in fake.requests)
    assert first["tool_choice"] == {"type": "auto"}
    assert first["cache_control"] == {"type": "ephemeral"}


def test_all_tool_results_go_back_together_first_and_matching(tmp_path: Path) -> None:
    script = [
        response(
            [
                text("Looking."),
                tool_use("a", "read_sheet", {"sheet_id": "x"}),
                tool_use("b", "read_transcript", {"clip": "c01"}),
            ],
            "tool_use",
        ),
        response([tool_use("c", "write_edl", GOOD_EDL)], "tool_use"),
    ]
    _, fake, _ = _run(tmp_path, script)

    reply = fake.requests[1]["messages"][-1]
    assert reply["role"] == "user"
    assert [b["type"] for b in reply["content"]] == ["tool_result", "tool_result"]
    assert [b["tool_use_id"] for b in reply["content"]] == ["a", "b"]
    assert all(b["is_error"] for b in reply["content"])


def test_end_turn_without_an_edit_list_gets_one_nudge_and_counts(tmp_path: Path) -> None:
    script = [
        response([text("I think it is done.")], "end_turn"),
        response([tool_use("t", "write_edl", GOOD_EDL)], "tool_use"),
    ]
    outcome, fake, _ = _run(tmp_path, script)

    nudge = fake.requests[1]["messages"][-1]
    assert nudge == {"role": "user", "content": NUDGE}
    assert outcome.turns == 2


def test_max_tokens_drops_the_cut_turn_and_retries_once_with_more_room(tmp_path: Path) -> None:
    script = [
        response([tool_use("cut", "read_sheet", {})], "max_tokens"),
        response([tool_use("t", "write_edl", GOOD_EDL)], "tool_use"),
    ]
    outcome, fake, _ = _run(tmp_path, script)
    editor = config.load().limits.editor

    assert outcome.edl is not None
    assert fake.requests[1]["max_tokens"] == editor.max_tokens_retry
    assert fake.requests[1]["messages"] == fake.requests[0]["messages"]  # the cut turn was not kept


def test_a_second_cut_off_is_output_too_long(tmp_path: Path) -> None:
    script = [response([text("...")], "max_tokens"), response([text("...")], "max_tokens")]

    with pytest.raises(OutputTooLong):
        _run(tmp_path, script)


@pytest.mark.parametrize("stop", ["refusal", "pause_turn", "something_new"])
def test_refusal_and_unknown_stops_fail_the_order(tmp_path: Path, stop: str) -> None:
    with pytest.raises(ModelRefusal, match=stop):
        _run(tmp_path, [response([text("No.")], stop)])


def test_no_edit_list_within_the_turn_limit_fails(tmp_path: Path) -> None:
    turns = config.load().limits.editor.max_turns
    script = [
        response([tool_use(f"t{i}", "read_sheet", {"sheet_id": "x"})], "tool_use")
        for i in range(turns)
    ]

    with pytest.raises(ModelRefusal, match="no edit list"):
        _run(tmp_path, script)


def test_the_guard_stops_a_call_that_could_cross_the_cap(tmp_path: Path) -> None:
    with pytest.raises(CostCapReached):
        _run(tmp_path, [response([text("x")], "end_turn")], cap="0.01")


def test_one_log_line_per_call_with_the_run_record_fields(tmp_path: Path) -> None:
    script = [
        response([tool_use("a", "read_sheet", {"sheet_id": "x"})], "tool_use"),
        response([tool_use("b", "write_edl", GOOD_EDL)], "tool_use"),
    ]
    _run(tmp_path, script)

    lines = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert len(lines) == 2
    fields = {
        "ts",
        "call",
        "model",
        "turn",
        "input_tokens",
        "cache_write",
        "cache_read",
        "output_tokens",
        "cost_usd",
        "spent_usd",
        "stop_reason",
        "latency_ms",
        "tools",
        "request_id",
    }
    assert fields <= set(lines[0])
    assert lines[0]["tools"] == ["read_sheet"] and lines[0]["call"] == "editor"
    assert lines[1]["turn"] == 2


def test_a_continued_conversation_puts_the_new_text_after_the_last_tool_results(
    tmp_path: Path,
) -> None:
    first, fake, box = _run(
        tmp_path, [response([tool_use("t1", "write_edl", GOOD_EDL)], "tool_use")]
    )
    fake.script = [response([tool_use("t2", "write_edl", GOOD_EDL)], "tool_use")]

    loop.run(_session(tmp_path, fake), box, "SYSTEM PROMPT", "Revise.", first.messages)

    messages = fake.requests[-1]["messages"]
    roles = [m["role"] for m in messages]
    assert all(a != b for a, b in itertools.pairwise(roles))  # strictly alternating
    last = messages[-1]["content"]
    assert [b["type"] for b in last] == ["tool_result", "text"] and last[-1]["text"] == "Revise."


def test_an_empty_end_turn_is_not_sent_back(tmp_path: Path) -> None:
    script = [
        response([], "end_turn"),
        response([tool_use("w", "write_edl", GOOD_EDL)], "tool_use"),
    ]

    _, fake, _ = _run(tmp_path, script)

    messages = fake.requests[1]["messages"]
    assert all(m["content"] for m in messages)
    roles = [m["role"] for m in messages]
    assert all(a != b for a, b in itertools.pairwise(roles))
    assert messages[-1]["content"][-1] == {"type": "text", "text": NUDGE}


def test_earlier_messages_stay_byte_equal_between_requests(tmp_path: Path) -> None:
    script = [
        response([tool_use("a", "read_transcript", {"clip": "c01"})], "tool_use"),
        response([text("Thinking.")], "end_turn"),
        response([tool_use("w", "write_edl", GOOD_EDL)], "tool_use"),
    ]

    _, fake, _ = _run(tmp_path, script)

    for before, after in itertools.pairwise(fake.requests):
        kept = after["messages"][: len(before["messages"]) - 1]
        assert json.dumps(kept) == json.dumps(before["messages"][: len(kept)])


def test_the_guard_counts_the_whole_request(tmp_path: Path) -> None:
    _, fake, _ = _run(tmp_path, [response([tool_use("w", "write_edl", GOOD_EDL)], "tool_use")])

    counted, sent = fake.counted[0], fake.requests[0]
    assert counted == {k: sent[k] for k in ("model", "system", "messages", "tools")}


def test_null_cache_counts_cost_nothing_but_missing_usage_is_an_error() -> None:
    usage = {"input_tokens": 10, "output_tokens": 5}
    nulls = {"cache_creation_input_tokens": None, "cache_read_input_tokens": None}

    counted = loop.usage_of({"usage": {**usage, **nulls}})

    assert (counted.cache_write, counted.cache_read, counted.input_tokens) == (0, 0, 10)
    with pytest.raises(KeyError):
        loop.usage_of({"usage": {"output_tokens": 5}})
