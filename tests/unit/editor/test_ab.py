"""The A/B harness (STEP-04, docs/EDITOR.md §11): same inputs and order, one judge for both
engines, a budget ledger that survives a crash, and a blind pick the step04 gate can read."""

import json
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.core.errors import RenderError, SpendLimitReached
from reel_studio.editor import ab, ab_judge, ab_kit, ab_pick, make
from tests.fakes.claude import FakeClaude
from tests.fakes.clock import FrozenClock
from tests.fakes.media import FakeMedia, critic_turn, edl_turn

CFG = config.load()
AB = CFG.limits.eval.ab
NOW = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)
GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"
EMPTY_TIMELINE = {"files": {}, "duration": 4.0, "planned_duration": 4.0, "segments": [], "text": []}


def _gate_ab_problems(data: object) -> list[str]:
    sys.path.insert(0, str(GATES))
    try:
        gate: Any = __import__("_gate")  # Any: a script module outside the package
    finally:
        sys.path.remove(str(GATES))
    problems: list[str] = gate.ab_problems(data, len(AB.fixtures))
    return problems


def _touch(folder: Path, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def _json(path: Path) -> dict[str, Any]:  # Any: JSON
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    return data


# ------------------------------------------------------------------ inputs


def test_inputs_are_media_only_videos_first_up_to_the_kit_limit(tmp_path: Path) -> None:
    _touch(
        tmp_path, "b.jpeg", "a.jpeg", "IMG_2.mov", "IMG_1.MOV", ".DS_Store", "notes.txt", "c.mp4"
    )

    picked = ab.select_inputs(tmp_path, max_files=4)

    assert [p.name for p in picked] == ["IMG_1.MOV", "IMG_2.mov", "c.mp4", "a.jpeg"]


def test_staged_inputs_are_links_and_a_second_stage_is_harmless(tmp_path: Path) -> None:
    source = tmp_path / "fixture"
    _touch(source, "IMG_1.mov", "IMG_2.mov")

    ab.stage(sorted(source.iterdir()), tmp_path / "staged")
    staged = ab.stage(sorted(source.iterdir()), tmp_path / "staged")

    assert all(p.is_symlink() for p in staged.iterdir())
    assert sorted(p.name for p in source.iterdir()) == ["IMG_1.mov", "IMG_2.mov"]


def test_one_order_for_the_engine_the_kit_and_the_judge() -> None:
    order = ab.order_for(CFG)

    assert (order.style, order.length_s, order.voice) == (AB.style, 30, False)
    context = ab_kit.context_for(order, "English")
    assert "30 s" in context and "English" in context and "voice" in context.lower()


# ------------------------------------------------------------------ the old kit's own command


def _stub_kit(root: Path, mode: str = "ok") -> Path:
    """A stand-in for the kit: its python is ours, make_reel.py is a stub that behaves like it."""
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").symlink_to(sys.executable)
    script = f'''
import json, os, sys
from pathlib import Path
root = Path(__file__).parent
args = sys.argv[1:]
(root / "seen.json").write_text(json.dumps({{
    "args": args,
    "cap": os.environ.get("REEL_MAX_BUDGET_USD"),
    "model": os.environ.get("REEL_MODEL"),
    "stdin": sys.stdin.read(),
}}))
if "--dry-run" in args:
    print("[reel] Dry run. Setup: OK")
    sys.exit(0)
job = args[args.index("--name") + 1] + "-1a2b"
print(f"[reel] Job {{job}}: model x, budget cap $2.")
(root / "runs").mkdir(exist_ok=True)
result = {{"type": "ResultMessage", "subtype": "success", "total_cost_usd": 0.9523169,
          "result": "done"}}
if "{mode}" == "budget":
    result.update(subtype="error_max_budget_usd", result="")
if "{mode}" == "refused":
    result.update(is_error=True, api_error_status=400, total_cost_usd=0, result="API Error: 400")
if "{mode}" == "cut":
    result.update(total_cost_usd=None)
lines = [{{"type": "SystemMessage"}}] + ([] if "{mode}" == "killed" else [result])
(root / "runs" / f"{{job}}.jsonl").write_text("\\n".join(json.dumps(x) for x in lines))
if "{mode}" == "ok":
    out = root / "output" / job
    out.mkdir(parents=True)
    for kind in ("text", "clean"):
        (out / f"{{job}}_{{kind}}.mp4").write_bytes(b"old")
    review = root / "work" / job / "review"
    review.mkdir(parents=True)
    (review / f"{{job}}.timeline.json").write_text(json.dumps({json.dumps(EMPTY_TIMELINE)}))
'''
    (root / "make_reel.py").write_text(script, encoding="utf-8")
    return root


def _kit(root: Path) -> ab_kit.OldKit:
    return ab_kit.OldKit(root, "claude-sonnet-5-5", AB.kit_timeout_s, AB.log_tail_chars)


def test_the_kit_runs_its_own_command_with_the_cap_the_model_and_no_stdin(tmp_path: Path) -> None:
    kit_root = _stub_kit(tmp_path / "kit")
    files = [tmp_path / "in dir" / "IMG_1.mov"]
    _touch(files[0].parent, "IMG_1.mov")

    run = _kit(kit_root).run("abcreami", files, Decimal("2.5"), "Target length 30 s.")

    seen = json.loads((kit_root / "seen.json").read_text())
    assert seen["args"] == [str(files[0]), "--name", "abcreami", "--context", "Target length 30 s."]
    assert (seen["cap"], seen["model"], seen["stdin"]) == ("2.5", "claude-sonnet-5-5", "")
    assert run.error is None and run.cost_usd == Decimal("0.9523169")
    assert run.text is not None and run.text.is_file() and run.timeline is not None


def test_a_kit_run_over_its_budget_is_an_error_with_its_cost_and_reason(tmp_path: Path) -> None:
    run = _kit(_stub_kit(tmp_path / "kit", "budget")).run("abx", [tmp_path], Decimal("2.5"), "")

    assert run.error is not None and "error_max_budget_usd" in run.error
    assert run.cost_usd == Decimal("0.9523169")


def test_a_killed_kit_run_counts_its_cap_as_spent(tmp_path: Path) -> None:
    run = _kit(_stub_kit(tmp_path / "kit", "killed")).run("abx", [tmp_path], Decimal("2.5"), "")

    assert run.error is not None and run.cost_usd == Decimal("2.5")


def test_the_kit_preflight_is_its_dry_run(tmp_path: Path) -> None:
    kit_root = _stub_kit(tmp_path / "kit")

    assert _kit(kit_root).check([tmp_path]) is None
    assert "--dry-run" in json.loads((kit_root / "seen.json").read_text())["args"]
    assert _kit(tmp_path / "nowhere").check([tmp_path]) is not None


# ------------------------------------------------------------------ the harness


class FakeKit:
    def __init__(self, cost: str = "0.95", fail: set[str] | None = None) -> None:
        self.calls: list[tuple[str, list[Path], Decimal, str]] = []
        self.cost, self.fail = Decimal(cost), fail if fail is not None else set()

    def check(self, files: list[Path]) -> str | None:
        return None

    def run(self, name: str, files: list[Path], cap: Decimal, context: str) -> ab_kit.KitRun:
        self.calls.append((name, files, cap, context))
        folder = files[0].parent.parent / f"kit-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        for out in ("text.mp4", "clean.mp4"):
            (folder / out).write_bytes(b"old")
        timeline = folder / "timeline.json"
        timeline.write_text(json.dumps(EMPTY_TIMELINE))
        error = "kit exit 1" if name in self.fail else None
        text, clean = folder / "text.mp4", folder / "clean.mp4"
        return ab_kit.KitRun(f"{name}-1a2b", self.cost, 300.0, text, clean, timeline, error)


class FakeJudge:
    def __init__(self, raise_on: int | None = None, error: Exception | None = None) -> None:
        self.calls: list[ab_judge.Cut] = []
        self.raise_on, self.error = raise_on, error

    def __call__(self, cut: ab_judge.Cut, folder: Path) -> ab_judge.Judged:
        self.calls.append(cut)
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise self.error if self.error is not None else RenderError("ffmpeg exited 1")
        return ab_judge.Judged(total=27, passed=True, cost_usd=Decimal("0.05"), weakness=None)


def _five_new_runs() -> list[Any]:
    return [turn for _ in range(5) for turn in (edl_turn("e1"), critic_turn(5))]


def _harness(
    tmp_path: Path,
    kit: FakeKit,
    judge: FakeJudge,
    *,
    script: list[Any] | None = None,
) -> ab.Harness:
    fixtures = tmp_path / "fixtures"
    for name in AB.fixtures:
        _touch(fixtures / name, "IMG_1.mov", "IMG_2.mov")
    media = FakeMedia()
    claude = FakeClaude(script if script is not None else _five_new_runs())
    return ab.Harness(
        cfg=CFG,
        fixtures=fixtures,
        root=tmp_path / "repo",
        ports=make.Ports(claude, FrozenClock(NOW)),
        steps_for=lambda _folder: make.Steps(media.prepare, media.render),
        kit=kit,
        judge=judge,
    )


def test_both_engines_run_on_the_same_files_and_one_judge_scores_both(tmp_path: Path) -> None:
    kit, judge = FakeKit(), FakeJudge()

    runs = _harness(tmp_path, kit, judge).run()

    data = _json(runs)
    assert [row["name"] for row in data["fixtures"]] == list(AB.fixtures)
    assert len(judge.calls) == 10  # the new engine's shipped render too, not its in-loop score
    for name, files, _cap, context in kit.calls:
        assert [f.name for f in files] == ["IMG_1.mov", "IMG_2.mov"], name
        assert "30 s" in context
    row = data["fixtures"][0]
    assert row["new"]["critic_total"] == 27 and row["new"]["loop_critic_total"] == 29
    assert row["old"]["cost_usd"] == Decimal("1.00")  # kit 0.95 + judge 0.05
    assert not Path(row["old"]["outputs"]["text"]).is_absolute()
    assert runs.name == "ab-runs.json" and runs.parent.name == "2026-10-12"


def test_a_failing_arm_is_recorded_and_the_rest_still_runs(tmp_path: Path) -> None:
    runs = _harness(tmp_path, FakeKit(), FakeJudge(raise_on=4)).run()

    rows = _json(runs)["fixtures"]
    errors = [(r["name"], side) for r in rows for side in ("new", "old") if r[side]["error"]]
    assert errors == [(AB.fixtures[1], "old")] and len(rows) == 5


def test_a_spend_limit_stops_the_run_after_writing_what_was_spent(tmp_path: Path) -> None:
    judge = FakeJudge(raise_on=2, error=SpendLimitReached("workspace limit"))

    with pytest.raises(SpendLimitReached):
        _harness(tmp_path, FakeKit(), judge).run()

    runs = tmp_path / "repo" / "eval" / "results" / "2026-10-12" / "ab-runs.json"
    rows = _json(runs)["fixtures"]
    assert rows[0]["new"]["error"] is None and rows[0]["old"]["error"] == "spend_limit"
    assert rows[0]["old"]["cost_usd"] == Decimal("0.95")


def test_a_second_run_resumes_and_reruns_only_failed_arms(tmp_path: Path) -> None:
    _harness(tmp_path, FakeKit(fail={f"ab{AB.fixtures[2]}"}), FakeJudge()).run()
    kit = FakeKit()

    runs = _harness(tmp_path, kit, FakeJudge(), script=[]).run()

    assert [name for name, *_ in kit.calls] == [f"ab{AB.fixtures[2]}"]
    rows = _json(runs)["fixtures"]
    assert all(r[side]["error"] is None for r in rows for side in ("new", "old"))


def test_the_budget_counts_earlier_runs_and_stops_before_a_run_that_could_pass_it(
    tmp_path: Path,
) -> None:
    small = AB.model_copy(update={"budget_usd": Decimal("3.20")})
    evals = CFG.limits.eval.model_copy(update={"ab": small})
    cfg = CFG.model_copy(update={"limits": CFG.limits.model_copy(update={"eval": evals})})

    harness = _harness(tmp_path, FakeKit(), FakeJudge())
    harness.cfg = cfg
    runs = harness.run()

    data = _json(runs)
    spent = sum(r[s]["cost_usd"] for r in data["fixtures"] for s in ("new", "old") if s in r)
    assert spent <= Decimal("3.20") and "budget" in data["stopped"]


def test_a_failed_preflight_spends_nothing(tmp_path: Path) -> None:
    class Broken(FakeKit):
        def check(self, files: list[Path]) -> str | None:
            return "kit python not found"

    fake = FakeClaude([])
    harness = _harness(tmp_path, Broken(), FakeJudge(), script=[])
    harness.ports = make.Ports(fake, FrozenClock(NOW))

    with pytest.raises(ab.PreflightError, match="kit python"):
        harness.run()

    assert fake.requests == [] and fake.counted == []


def test_only_limits_the_run_to_the_named_fixtures(tmp_path: Path) -> None:
    kit = FakeKit()
    script = [edl_turn("e1"), critic_turn(5)]

    harness = _harness(tmp_path, kit, FakeJudge(), script=script)
    harness.only = (AB.fixtures[0],)
    runs = harness.run()

    assert [name for name, *_ in kit.calls] == [f"ab{AB.fixtures[0]}"]
    assert [r["name"] for r in _json(runs)["fixtures"]] == [AB.fixtures[0]]


def test_a_later_day_carries_the_rows_and_does_not_pay_twice(tmp_path: Path) -> None:
    first = _harness(tmp_path, FakeKit(), FakeJudge()).run()
    spent = _json(first)["spent_usd"]
    kit = FakeKit()
    later = _harness(tmp_path, kit, FakeJudge(), script=[])
    later.ports = make.Ports(FakeClaude([]), FrozenClock(NOW.replace(day=13)))

    runs = later.run()

    data = _json(runs)
    assert runs.parent.name == "2026-10-13" and kit.calls == []
    assert len(data["fixtures"]) == 5 and data["spent_usd"] == spent


def test_redo_reruns_a_finished_fixture_and_keeps_the_earlier_attempt(tmp_path: Path) -> None:
    _harness(tmp_path, FakeKit(), FakeJudge()).run()
    kit = FakeKit()
    again = _harness(tmp_path, kit, FakeJudge(), script=[edl_turn("e1"), critic_turn(5)])
    again.redo = (AB.fixtures[0],)

    runs = again.run()

    row = _json(runs)["fixtures"][0]
    assert [name for name, *_ in kit.calls] == [f"ab{AB.fixtures[0]}"]
    assert [a["side"] for a in row["attempts"]] == ["new", "old"]
    assert row["old"]["cost_usd"] == Decimal("2.00")  # the earlier paid try stays on the ledger


def test_an_unknown_fixture_name_is_refused_before_any_spend(tmp_path: Path) -> None:
    harness = _harness(tmp_path, FakeKit(), FakeJudge(), script=[])
    harness.only = ("nope",)

    with pytest.raises(ab.PreflightError, match="nope"):
        harness.run()


def test_the_ledger_counts_a_carried_arm_once_on_every_later_load(tmp_path: Path) -> None:
    spent = _json(_harness(tmp_path, FakeKit(), FakeJudge()).run())["spent_usd"]
    for day in (13, 14):
        later = _harness(tmp_path, FakeKit(), FakeJudge(), script=[])
        later.ports = make.Ports(FakeClaude([]), FrozenClock(NOW.replace(day=day)))
        assert _json(later.run())["spent_usd"] == spent


def test_a_refused_kit_stops_the_harness_with_its_cost_on_the_ledger(tmp_path: Path) -> None:
    class Refused(FakeKit):
        def run(self, name: str, files: list[Path], cap: Decimal, context: str) -> ab_kit.KitRun:
            raise ab_kit.KitRefused("kit API error 400", Decimal("0.01"))

    with pytest.raises(ab_kit.KitRefused):
        _harness(tmp_path, Refused(), FakeJudge()).run()

    rows = _json(tmp_path / "repo" / "eval" / "results" / "2026-10-12" / "ab-runs.json")["fixtures"]
    assert len(rows) == 1 and rows[0]["old"]["error"] == "KitRefused"
    assert rows[0]["old"]["cost_usd"] == Decimal("0.01")


# ------------------------------------------------------------------ the blind pick and the report


def _picked(tmp_path: Path, answers: list[str], seed: int, said: list[str]) -> Path:
    runs = _harness(tmp_path, FakeKit(), FakeJudge()).run()
    it = iter(answers)
    return ab_pick.pick(runs, tmp_path / "repo", lambda _p: next(it), seed, said.append)


def test_picks_turn_the_runs_into_the_file_the_gate_reads(tmp_path: Path) -> None:
    said: list[str] = []
    result = _picked(tmp_path, ["x", "Sharper hook", "tie", "Same"] + ["y", "r"] * 3, 7, said)

    data = _json(result)
    assert result.name == "ab.json" and _gate_ab_problems(data) == []
    assert data["fixtures"][1]["pick"] == "tie" and data["fixtures"][0]["reason"] == "Sharper hook"


def test_nothing_before_the_reveal_says_which_engine_is_which(tmp_path: Path) -> None:
    said: list[str] = []
    _picked(tmp_path, ["x", "r"] * 5, 7, said)

    reveal = next(i for i, line in enumerate(said) if " was " in line)
    before = " ".join(said[:reveal]).lower()
    page = (tmp_path / "repo" / "out" / "ab" / "2026-10-12" / "pick" / "pick.html").read_text()
    for text in (before, page.lower()):
        assert not re.search(r"\b(new|old)\b|kit-|/new-|/old-", text)


def test_x_maps_to_the_shuffled_first_side_and_the_order_varies(tmp_path: Path) -> None:
    firsts = {ab_pick.order_of(seed, list(AB.fixtures))[AB.fixtures[0]][0] for seed in range(20)}
    said: list[str] = []
    data = _json(_picked(tmp_path, ["x", "r"] * 5, 7, said))

    expected = ab_pick.order_of(7, list(AB.fixtures))
    assert firsts == {"new", "old"}
    assert [r["pick"] for r in data["fixtures"]] == [expected[n][0] for n in AB.fixtures]


def test_a_pick_must_be_x_y_or_tie(tmp_path: Path) -> None:
    said: list[str] = []
    _picked(tmp_path, ["maybe", "x", "r"] + ["tie", "r"] * 4, 1, said)

    assert any("x, y or tie" in line for line in said)


def test_pick_names_fixtures_that_never_ran(tmp_path: Path) -> None:
    harness = _harness(tmp_path, FakeKit(), FakeJudge(), script=[edl_turn("e1"), critic_turn(5)])
    harness.only = (AB.fixtures[0],)
    runs = harness.run()

    with pytest.raises(ab_pick.Incomplete, match=AB.fixtures[4]):
        ab_pick.pick(runs, tmp_path / "repo", lambda _p: "x", 1, lambda _l: None)


def test_pick_refuses_while_an_arm_failed_and_names_the_fixture(tmp_path: Path) -> None:
    runs = _harness(tmp_path, FakeKit(fail={f"ab{AB.fixtures[3]}"}), FakeJudge()).run()

    with pytest.raises(ab_pick.Incomplete, match=AB.fixtures[3]):
        ab_pick.pick(runs, tmp_path / "repo", lambda _p: "x", 1, lambda _l: None)


def test_the_report_has_every_fixture_the_verdict_and_the_budget(tmp_path: Path) -> None:
    said: list[str] = []
    _picked(tmp_path, ["x", "a | b"] * 5, 3, said)

    report = (tmp_path / "repo" / "eval" / "AB-RESULT.md").read_text(encoding="utf-8")

    for name in AB.fixtures:
        assert f"| {name} |" in report
    assert "Verdict: PASS" in report or "Verdict: FAIL" in report
    assert "a / b" in report  # a reason cannot break the table
    assert "budget" in report.lower()


def test_a_refused_kit_key_stops_the_run_with_its_cost_recorded(tmp_path: Path) -> None:
    """The kit's 7 Oct log: a 400 'key not scoped to a workspace' at $0; five fixtures would
    each pay for a new arm before failing the same way."""
    run = _stub_kit(tmp_path / "kit", "refused")

    with pytest.raises(ab_kit.KitRefused, match="400"):
        _kit(run).run("abx", [tmp_path], Decimal("2.5"), "")


def test_a_cut_off_log_counts_the_cap(tmp_path: Path) -> None:
    run = _kit(_stub_kit(tmp_path / "kit", "cut")).run("abx", [tmp_path], Decimal("2.5"), "")

    assert run.cost_usd == Decimal("2.5") and run.error is not None


def test_before_the_picks_the_report_says_pending_and_shows_the_other_checks(
    tmp_path: Path,
) -> None:
    runs = _harness(tmp_path, FakeKit(), FakeJudge()).run()

    report = ab_pick.write_pending(runs, tmp_path / "repo").read_text(encoding="utf-8")

    assert "Verdict: pending Kevin's blind picks" in report
    assert "mean critic new" in report and "picked or tied" not in report


def test_an_interrupted_kit_arm_stays_on_the_ledger_at_its_cap(tmp_path: Path) -> None:
    class Interrupted(FakeKit):
        def run(self, name: str, files: list[Path], cap: Decimal, context: str) -> ab_kit.KitRun:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _harness(tmp_path, Interrupted(), FakeJudge()).run()

    rows = _json(tmp_path / "repo" / "eval" / "results" / "2026-10-12" / "ab-runs.json")["fixtures"]
    assert rows[0]["old"]["cost_usd"] == AB.kit_run_cap_usd


def test_the_pending_report_asks_for_the_picks_before_the_scores(tmp_path: Path) -> None:
    runs = _harness(tmp_path, FakeKit(), FakeJudge()).run()

    report = ab_pick.write_pending(runs, tmp_path / "repo").read_text(encoding="utf-8")

    assert report.index("make ab-pick` before reading") < report.index("| fixture |")


def test_redo_of_one_side_keeps_the_other_sides_cut_and_pays_nothing_for_it(
    tmp_path: Path,
) -> None:
    """Round 2 tunes our prompts only: the kit's finished cuts stay, only the new arm reruns."""
    first = _json(_harness(tmp_path, FakeKit(), FakeJudge()).run())["fixtures"][0]
    kit = FakeKit()
    again = _harness(tmp_path, kit, FakeJudge(), script=[edl_turn("e1"), critic_turn(5)])
    again.redo = (f"{AB.fixtures[0]}:new",)

    runs = again.run()

    row = _json(runs)["fixtures"][0]
    assert kit.calls == []
    assert row["old"] == first["old"]
    assert [a["side"] for a in row["attempts"]] == ["new"]
    assert row["new"]["error"] is None


def test_redo_names_a_side_that_exists() -> None:
    assert ab.parse_redo("cookies:new,meat") == (("cookies", ("new",)), ("meat", ab.SIDES))
    with pytest.raises(ab.PreflightError, match="side"):
        ab.parse_redo("cookies:kit")
