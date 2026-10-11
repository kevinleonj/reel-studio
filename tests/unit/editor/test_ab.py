"""The A/B harness (STEP-04, docs/EDITOR.md §11): same inputs, same judge, a budget guard,
and a result file the step04 gate can read once Kevin's blind picks are in."""

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.editor import ab, ab_pick, make
from tests.fakes.claude import FakeClaude
from tests.fakes.clock import FrozenClock
from tests.fakes.media import FakeMedia, critic_turn, edl_turn

CFG = config.load()
NOW = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)
GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"


def _gate_ab_problems(data: object) -> list[str]:
    sys.path.insert(0, str(GATES))
    try:
        gate: Any = __import__("_gate")  # Any: a script module outside the package
    finally:
        sys.path.remove(str(GATES))
    problems: list[str] = gate.ab_problems(data, len(CFG.limits.eval.ab.fixtures))
    return problems


def _touch(folder: Path, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def test_inputs_are_videos_first_then_photos_up_to_the_kit_limit(tmp_path: Path) -> None:
    _touch(tmp_path, "b.jpeg", "a.jpeg", "IMG_2.mov", "IMG_1.MOV", ".DS_Store", "clip.mp4")

    picked = ab.select_inputs(tmp_path, max_files=4)

    assert [p.name for p in picked] == ["IMG_1.MOV", "IMG_2.mov", "clip.mp4", "a.jpeg"]


def test_staged_inputs_are_links_and_the_fixture_is_untouched(tmp_path: Path) -> None:
    source = tmp_path / "fixture"
    _touch(source, "IMG_1.mov", "IMG_2.mov")
    before = sorted(p.name for p in source.iterdir())

    staged = ab.stage(sorted(source.iterdir()), tmp_path / "staged")

    assert sorted(p.name for p in staged.iterdir()) == before
    assert all(p.is_symlink() for p in staged.iterdir())
    assert sorted(p.name for p in source.iterdir()) == before


class FakeKit:
    """Stands in for the old kit's make_reel.py: records the call, returns a finished run."""

    def __init__(self, cost: str = "0.95") -> None:
        self.calls: list[tuple[str, list[Path], Decimal]] = []
        self.cost = Decimal(cost)

    def run(self, name: str, files: list[Path], cap: Decimal) -> ab.KitRun:
        self.calls.append((name, files, cap))
        folder = Path(files[0]).parent.parent / f"kit-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        for out in ("text.mp4", "clean.mp4"):
            (folder / out).write_bytes(b"old")
        return ab.KitRun(
            job=f"{name}-1a2b",
            cost_usd=self.cost,
            wall_s=300.0,
            text=folder / "text.mp4",
            clean=folder / "clean.mp4",
            timeline=None,
            error=None,
        )


def _harness(tmp_path: Path, kit: FakeKit, script: list[Any], cfg: config.Config = CFG) -> Path:
    fixtures = tmp_path / "fixtures"
    for name in cfg.limits.eval.ab.fixtures:
        _touch(fixtures / name, "IMG_1.mov", "IMG_2.mov")
    fake, media = FakeClaude(script), FakeMedia()

    def judge_old(run: ab.KitRun, folder: Path) -> ab.Judged:
        return ab.Judged(total=27, passed=True, cost_usd=Decimal("0.05"), weakness=None)

    harness = ab.Harness(
        cfg=cfg,
        fixtures=fixtures,
        root=tmp_path / "repo",
        ports=make.Ports(fake, FrozenClock(NOW)),
        steps_for=lambda _folder: make.Steps(media.prepare, media.render),
        kit=kit,
        judge_old=judge_old,
    )
    return harness.run()


def _five_new_runs() -> list[Any]:
    return [turn for _ in range(5) for turn in (edl_turn("e1"), critic_turn(5))]


def test_every_fixture_runs_both_engines_and_the_runs_file_is_written(tmp_path: Path) -> None:
    kit = FakeKit()

    runs = _harness(tmp_path, kit, _five_new_runs())

    data = json.loads(runs.read_text(encoding="utf-8"), parse_float=Decimal)
    names = [row["name"] for row in data["fixtures"]]
    assert names == list(CFG.limits.eval.ab.fixtures) and len(kit.calls) == 5
    row = data["fixtures"][0]
    assert row["new"]["critic_total"] == 29 and row["new"]["passed"] is True
    assert row["old"]["critic_total"] == 27 and row["old"]["cost_usd"] == Decimal("1.00")
    assert "pick" not in row  # Kevin's blind pick comes later (make ab-pick)
    assert runs.name == "ab-runs.json" and runs.parent.name == "2026-10-12"


def test_both_engines_get_the_same_files(tmp_path: Path) -> None:
    kit = FakeKit()

    _harness(tmp_path, kit, _five_new_runs())

    for name, files, _cap in kit.calls:
        assert [f.name for f in files] == ["IMG_1.mov", "IMG_2.mov"], name


def test_the_harness_stops_before_a_run_that_could_pass_the_budget(tmp_path: Path) -> None:
    small = CFG.limits.eval.ab.model_copy(update={"budget_usd": Decimal("3.00")})
    evals = CFG.limits.eval.model_copy(update={"ab": small})
    cfg = CFG.model_copy(update={"limits": CFG.limits.model_copy(update={"eval": evals})})
    kit = FakeKit(cost="0.95")

    runs = _harness(tmp_path, kit, _five_new_runs(), cfg)

    data = json.loads(runs.read_text(encoding="utf-8"), parse_float=Decimal)
    spent = sum(
        row[side]["cost_usd"]
        for row in data["fixtures"]
        for side in ("new", "old")
        if row.get(side)
    )
    assert spent <= Decimal("3.00")
    assert data["stopped"] is not None and "budget" in data["stopped"]


def test_picks_turn_the_runs_into_the_file_the_gate_reads(tmp_path: Path) -> None:
    runs = _harness(tmp_path, FakeKit(), _five_new_runs())
    answers = iter(["x", "Sharper hook", "tie", "Same", "y", "Better ending", "x", "", "y", "ok"])

    result = ab_pick.pick(
        runs, tmp_path / "repo", ask=lambda _prompt: next(answers), seed=7, say=lambda _line: None
    )

    data = json.loads(result.read_text(encoding="utf-8"), parse_float=Decimal)
    assert result.name == "ab.json" and _gate_ab_problems(data) == []
    assert {row["pick"] for row in data["fixtures"]} <= {"new", "old", "tie"}
    assert data["fixtures"][1]["pick"] == "tie" and data["fixtures"][0]["reason"] == "Sharper hook"


def test_a_pick_must_be_x_y_or_tie(tmp_path: Path) -> None:
    runs = _harness(tmp_path, FakeKit(), _five_new_runs())
    answers = iter(["maybe", "x", "r"] + ["tie", "r"] * 4)
    said: list[str] = []

    ab_pick.pick(
        runs, tmp_path / "repo", ask=lambda _prompt: next(answers), seed=1, say=said.append
    )

    assert any("x, y or tie" in line for line in said)


def test_the_report_has_a_row_per_fixture_and_the_verdict(tmp_path: Path) -> None:
    runs = _harness(tmp_path, FakeKit(), _five_new_runs())
    answers = iter(["x", "r", "y", "r", "tie", "r", "x", "r", "y", "r"])
    ab_pick.pick(
        runs, tmp_path / "repo", ask=lambda _prompt: next(answers), seed=3, say=lambda _line: None
    )

    report = (tmp_path / "repo" / "eval" / "AB-RESULT.md").read_text(encoding="utf-8")

    for name in CFG.limits.eval.ab.fixtures:
        assert f"| {name} |" in report
    assert "Verdict:" in report


def test_kit_cost_comes_from_the_result_message(tmp_path: Path) -> None:
    log = tmp_path / "run.jsonl"
    lines = [
        {"type": "SystemMessage"},
        {"type": "ResultMessage", "subtype": "success", "total_cost_usd": 0.9523169},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

    assert ab.kit_cost(log) == Decimal("0.9523169")


def test_a_kit_log_without_a_result_is_an_error(tmp_path: Path) -> None:
    log = tmp_path / "run.jsonl"
    log.write_text(json.dumps({"type": "SystemMessage"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no result"):
        ab.kit_cost(log)
