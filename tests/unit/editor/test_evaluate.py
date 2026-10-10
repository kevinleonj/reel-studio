"""`make eval` (STEP-03 task 8): one fixture through `make`, recorded in the gate's contract."""

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.core.config import Eval
from reel_studio.editor import evaluate, make
from tests.fakes.claude import FakeClaude, response, text, tool_use
from tests.fakes.clock import FrozenClock
from tests.fakes.media import FakeMedia, critic_turn, edl_turn

CFG = config.load()
NOW = datetime(2026, 10, 10, 18, 30, 5, tzinfo=UTC)
GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"
CACHED = {
    "input_tokens": 40,
    "output_tokens": 300,
    "cache_creation_input_tokens": 200,
    "cache_read_input_tokens": 9000,
}


def _gate_problems(data: object, fixture: str, model: str) -> list[str]:
    """The gate's own contract check, so this test fails when the file stops meeting it."""
    sys.path.insert(0, str(GATES))
    try:
        gate: Any = __import__("_gate")  # Any: a script module outside the package
    finally:
        sys.path.remove(str(GATES))
    problems: list[str] = gate.eval_problems(data, fixture, model)
    return problems


def _job(tmp_path: Path, model: str, fixture: str = "creami") -> evaluate.Job:
    return evaluate.Job(
        fixture=fixture,
        model=model,
        fixtures=tmp_path / "fixtures",
        root=tmp_path / "repo",
        style="montage",
    )


def _run(
    tmp_path: Path, script: list[Any], model: str, now: datetime = NOW
) -> tuple[int, FakeClaude, Path]:
    fake, media = FakeClaude(script), FakeMedia()
    (tmp_path / "fixtures" / "creami").mkdir(parents=True, exist_ok=True)
    ports = make.Ports(fake, FrozenClock(now))
    code = evaluate.run(_job(tmp_path, model), ports, make.Steps(media.prepare, media.render), CFG)
    return code, fake, tmp_path / "repo" / "eval" / "results" / "2026-10-10"


def _result(folder: Path, name: str) -> dict[str, Any]:  # Any: result JSON
    """Read as the gate reads it: numbers with a fraction become Decimal."""
    raw = (folder / name).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw, parse_float=Decimal)
    return data


def test_a_run_writes_the_result_the_gate_reads(tmp_path: Path) -> None:
    script = [edl_turn("e1"), critic_turn(5)]
    script[0]["usage"] = dict(CACHED)

    code, _, folder = _run(tmp_path, script, "sonnet")

    data = _result(folder, "creami-sonnet.json")
    assert code == 0
    assert _gate_problems(data, "creami", "sonnet") == []
    assert data["critic"] == {"total": 29, "passed": True, "weakness": None}
    assert data["requests"] == [
        {
            "input_tokens": 40,
            "output_tokens": 300,
            "cache_read_input_tokens": 9000,
            "cache_creation_input_tokens": 200,
        }
    ]
    assert len(data["critic_requests"]) == 1
    text_mp4 = data["outputs"]["text"]
    assert text_mp4.endswith("text.mp4") and not Path(text_mp4).is_absolute()


def test_cost_covers_every_call_critic_included(tmp_path: Path) -> None:
    _, _, folder = _run(tmp_path, [edl_turn("e1"), critic_turn(5)], "sonnet")

    data = _result(folder, "creami-sonnet.json")

    # FakeClaude's default usage: 10 input and 5 output tokens per call at $2 / $10 per million.
    one_call = (10 * Decimal(2) + 5 * Decimal(10)) / 1_000_000
    assert Decimal(str(data["cost_usd"])) == 2 * one_call


def test_haiku_runs_the_editor_and_the_critic_on_the_cheap_model(tmp_path: Path) -> None:
    _, fake, folder = _run(tmp_path, [edl_turn("e1"), critic_turn(5)], "haiku")

    assert {r["model"] for r in fake.requests} == {CFG.limits.editor.cheap_model}
    assert _result(folder, "creami-haiku.json")["model"] == "haiku"


def test_sonnet_uses_the_configured_editor_and_critic(tmp_path: Path) -> None:
    _, fake, _ = _run(tmp_path, [edl_turn("e1"), critic_turn(5)], "sonnet")

    editor = CFG.limits.editor
    assert [r["model"] for r in fake.requests] == [editor.model, editor.critic_model]


def test_a_failed_run_still_records_what_it_spent(tmp_path: Path) -> None:
    code, _, folder = _run(tmp_path, [response([text("No.")], "refusal")], "haiku")

    data = _result(folder, "creami-haiku.json")
    assert code == 1
    assert data["error"] == "model_refusal" and data["critic"]["passed"] is False
    assert Decimal(str(data["cost_usd"])) > 0 and len(data["requests"]) == 1
    assert _gate_problems(data, "creami", "haiku") == []


def test_a_second_run_the_same_day_keeps_the_first_runs_record(tmp_path: Path) -> None:
    _run(tmp_path, [edl_turn("e1"), critic_turn(3), edl_turn("e2"), critic_turn(3)], "haiku")

    later = NOW.replace(minute=45)
    _, _, folder = _run(tmp_path, [edl_turn("e1"), critic_turn(5)], "haiku", later)

    newest = _result(folder, "creami-haiku.json")
    first = _result(folder, "creami-haiku-183005.json")
    assert len(newest["requests"]) == 1 and len(newest["critic_requests"]) == 1
    assert len(first["requests"]) == 2 and first["critic"]["passed"] is False
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["creami-haiku-183005.json", "creami-haiku.json"]


def test_the_result_carries_every_score(tmp_path: Path) -> None:
    _, _, folder = _run(tmp_path, [edl_turn("e1"), critic_turn(5)], "haiku")

    scores = _result(folder, "creami-haiku.json")["scores"]

    assert scores["hook"] == 5 and sum(scores.values()) == 29


def test_a_run_stops_at_the_eval_cap_before_any_call(tmp_path: Path) -> None:
    tiny = Eval(run_cap_usd=Decimal("0.01"))
    capped = CFG.model_copy(update={"limits": CFG.limits.model_copy(update={"eval": tiny})})
    fake, media = FakeClaude([edl_turn("e1")]), FakeMedia()
    (tmp_path / "fixtures" / "creami").mkdir(parents=True)
    ports, steps = make.Ports(fake, FrozenClock(NOW)), make.Steps(media.prepare, media.render)

    code = evaluate.run(_job(tmp_path, "sonnet"), ports, steps, capped)

    data = _result(tmp_path / "repo" / "eval" / "results" / "2026-10-10", "creami-sonnet.json")
    assert code == 1 and fake.requests == [] and data["error"] == "cost_cap"


def test_an_unexpected_error_is_raised_after_its_spend_is_recorded(tmp_path: Path) -> None:
    looked = response([tool_use("t", "read_transcript", {"clip": "c01"})], "tool_use")

    with pytest.raises(RuntimeError, match="boom"):
        _run(tmp_path, [looked, RuntimeError("boom")], "haiku")

    data = _result(tmp_path / "repo" / "eval" / "results" / "2026-10-10", "creami-haiku.json")
    assert data["error"] == "RuntimeError" and len(data["requests"]) == 1
    assert _gate_problems(data, "creami", "haiku") == []


def test_an_unknown_model_or_fixture_is_refused(tmp_path: Path) -> None:
    (tmp_path / "fixtures").mkdir()
    media = FakeMedia()
    steps = make.Steps(media.prepare, media.render)
    fake = FakeClaude([])
    ports = make.Ports(fake, FrozenClock(NOW))

    with pytest.raises(ValueError, match="model"):
        evaluate.run(_job(tmp_path, "opus"), ports, steps, CFG)
    with pytest.raises(ValueError, match="fixture"):
        evaluate.run(_job(tmp_path, "haiku", fixture="nope"), ports, steps, CFG)
    assert fake.requests == []


def test_an_interrupted_run_still_records_what_it_spent(tmp_path: Path) -> None:
    """Ctrl-C during a paid run is the likeliest way to stop one: its calls still count."""
    looked = response([tool_use("t", "read_transcript", {"clip": "c01"})], "tool_use")

    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, [looked, KeyboardInterrupt()], "haiku")

    data = _result(tmp_path / "repo" / "eval" / "results" / "2026-10-10", "creami-haiku.json")
    assert data["error"] == "KeyboardInterrupt" and len(data["requests"]) == 1


def test_an_earlier_result_without_a_start_time_is_kept_by_its_file_time(tmp_path: Path) -> None:
    folder = tmp_path / "repo" / "eval" / "results" / "2026-10-10"
    folder.mkdir(parents=True)
    (folder / "creami-haiku.json").write_text('{"cost_usd": 0.01}\n', encoding="utf-8")

    _run(tmp_path, [edl_turn("e1"), critic_turn(5)], "haiku")

    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == 2 and "creami-haiku.json" in names
