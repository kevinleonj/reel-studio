"""`make ab` (STEP-04, docs/EDITOR.md §11): the new engine against the old kit on the same files.

Each fixture in limits.toml [eval.ab] gets the same files and the same order on both sides (the
kit takes at most 15 files, videos first). The new engine runs `make` with Sonnet; the old kit
runs its own make_reel.py (ab_kit). One judge (ab_judge) scores both finished cuts.

Money is guarded three ways: a free preflight before the first paid call; a ledger summed from
every ab-runs.json on disk, so a rerun cannot spend the budget twice; and ab-runs.json written
after every arm, so a crash keeps what was spent. A rerun skips finished arms and repeats failed
ones. An arm that fails is recorded with its cost and the run goes on; a spend limit, a refused
request or Ctrl-C stops it after the record is written.
"""

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from reel_studio.core import config, constants
from reel_studio.core.config import Config
from reel_studio.core.errors import ProviderRejected, ReelError, SpendLimitReached
from reel_studio.core.logging import configure, get_logger
from reel_studio.editor import ab_judge, ab_kit, evaluate, make, prompt
from reel_studio.editor.media import render
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.settings import BuildSettings, EditorSettings

log = get_logger(__name__)

STAGE = "ab"
RUNS_JSON = "ab-runs.json"
OUT = Path("out") / "ab"
SIDES = ("new", "old")
MEDIA_EXT = {e.lower() for e in (*constants.VIDEO_EXT, *constants.IMAGE_EXT)}
VIDEO_EXT = {e.lower() for e in constants.VIDEO_EXT}
STOPS = (
    SpendLimitReached,
    ProviderRejected,
    ab_kit.KitRefused,
    KeyboardInterrupt,
)  # recorded, then raised

type Row = dict[str, Any]  # Any: one fixture of ab-runs.json


class PreflightError(RuntimeError):
    """Something a paid run would hit, found before any money is spent."""


def select_inputs(folder: Path, max_files: int) -> list[Path]:
    """The files both engines get: media only, videos first, then photos, each by name."""
    files = sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXT and p.name not in constants.SKIP_NAMES
    )
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    return (videos + [p for p in files if p not in videos])[:max_files]


def stage(files: list[Path], folder: Path) -> Path:
    """A folder of links to `files`, so `make` reads exactly them and the fixture stays as it is."""
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        link = folder / f.name
        if not link.is_symlink() and not link.exists():
            link.symlink_to(f.resolve())
    return folder


def order_for(cfg: Config) -> prompt.OrderSettings:
    """The one order both engines and the judge get."""
    voice = False  # transcription arrives in STEP-05
    first = cfg.styles.text_languages.items[0].code
    return prompt.OrderSettings(
        cfg.limits.eval.ab.style, cfg.limits.order.default_length_s, first, voice
    )


def _arm(cost: Decimal, wall: float, error: str | None, **rest: object) -> Row:
    return {
        "critic_total": 0,
        "passed": False,
        **rest,
        "cost_usd": float(cost),
        "wall_s": round(wall, 1),
        "error": error,
    }


def _cost_on_disk(folder: Path) -> Decimal:
    """What the calls under `folder` cost (every requests.jsonl): the new arm and the judge."""
    return sum((evaluate.calls_of(p)[2] for p in folder.rglob(make.REQUESTS)), Decimal(0))


@dataclass
class Harness:
    cfg: Config
    fixtures: Path  # REEL_FIXTURES_DIR
    root: Path  # the repository
    ports: make.Ports
    steps_for: Callable[[Path], make.Steps]  # the render reads style photos from the folder
    kit: ab_kit.Kit
    judge: Callable[[ab_judge.Cut, Path], ab_judge.Judged]
    only: tuple[str, ...] = ()
    redo: tuple[str, ...] = ()  # fixtures whose finished arms run again (after a tune)
    spent: Decimal = Decimal(0)
    rows: list[Row] = field(default_factory=list)

    # ---------------------------------------------------------------- the ledger
    def _target(self, day: str) -> Path:
        return self.root / evaluate.RESULTS / day / RUNS_JSON

    def _load(self, day: str) -> None:
        """Rows of the newest ab-runs.json, and every arm's cost in every file on disk.

        Rows from an earlier day are carried into today's file marked `carried`; the ledger
        counts an arm only in the file where it was paid."""
        paths = sorted((self.root / evaluate.RESULTS).glob(f"*/{RUNS_JSON}"))
        for path in paths:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))  # Any: JSON
            for row in data["fixtures"]:
                arms = [row[s] for s in SIDES if s in row and not row[s].get("carried")]
                self.spent += sum((Decimal(str(a["cost_usd"])) for a in arms), Decimal(0))
        if not paths:
            return
        newest: dict[str, Any] = json.loads(paths[-1].read_text(encoding="utf-8"))  # Any: JSON
        self.rows = newest["fixtures"]
        if paths[-1] != self._target(day):
            for row in self.rows:
                for side in SIDES:
                    if side in row:
                        row[side]["carried"] = True

    def _write(self, day: str, stopped: str | None) -> Path:
        target = self._target(day)
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {"spent_usd": float(self.spent), "stopped": stopped, "fixtures": self.rows}
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        temporary.replace(target)  # a crash mid-write never leaves half a ledger
        return target

    # ---------------------------------------------------------------- the arms
    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def _new(self, files: list[Path], base: Path, out: Path) -> Row:
        folder = stage(files, base / "inputs")
        request = make.Request(folder, out, order_for(self.cfg))
        started = time.monotonic()
        made = make.make(
            request, self.ports, self.steps_for(folder), evaluate.for_eval(self.cfg, "sonnet")
        )
        cut = ab_judge.Cut(out / render.TEXT, out / render.CLEAN, made.final.render.timeline)
        judged = self.judge(cut, out / "judge")
        review = made.final.review
        return _arm(
            made.cost + judged.cost_usd,
            time.monotonic() - started,
            None,
            critic_total=judged.total,
            passed=judged.passed,
            weakness=judged.weakness,
            loop_critic_total=review.total if review is not None else None,
            outputs={"text": self._relative(out / render.TEXT)},
        )

    def _old(self, name: str, files: list[Path], folder: Path) -> Row:
        ab_cfg, order = self.cfg.limits.eval.ab, order_for(self.cfg)
        language = self.cfg.styles.text_languages.items[0].label
        run = self.kit.run(
            f"ab{name}", files, ab_cfg.kit_run_cap_usd, ab_kit.context_for(order, language)
        )
        if run.error is not None or run.text is None or run.clean is None or run.timeline is None:
            return _arm(
                run.cost_usd,
                run.wall_s,
                run.error if run.error is not None else "kit run without output",
                job=run.job,
            )
        try:
            folder.mkdir(parents=True, exist_ok=True)  # the kit's videos kept with the result
            text = Path(shutil.copy2(run.text, folder / render.TEXT))
            clean = Path(shutil.copy2(run.clean, folder / render.CLEAN))
            timeline = render.Timeline.model_validate_json(run.timeline.read_text(encoding="utf-8"))
            judged = self.judge(ab_judge.Cut(text, clean, timeline), folder / "judge")
        except BaseException as exc:
            exc.add_note(f"kit cost {run.cost_usd}")
            raise _ArmFailed(run.cost_usd) from exc
        return _arm(
            run.cost_usd + judged.cost_usd,
            run.wall_s,
            None,
            critic_total=judged.total,
            passed=judged.passed,
            weakness=judged.weakness,
            job=run.job,
            kit_cost_usd=float(run.cost_usd),
            outputs={"text": self._relative(folder / render.TEXT)},
        )

    def _contained(self, attempt: Path, call: Callable[[], Row]) -> Row:
        """Run one arm; any failure becomes a recorded arm with what it cost."""
        started = time.monotonic()
        try:
            return call()
        except BaseException as exc:  # noqa: BLE001 - recorded with its cost; run() re-raises stops
            paid = exc.__cause__ if isinstance(exc, _ArmFailed) else exc
            known = exc.cost if isinstance(exc, (_ArmFailed, ab_kit.KitRefused)) else Decimal(0)
            cost = known + _cost_on_disk(attempt)  # only this attempt's calls
            code = paid.code if isinstance(paid, ReelError) else type(paid).__name__
            log.error(
                "%s failed: %s",
                attempt.name,
                code,
                extra={"stage": STAGE, "event": "arm", "outcome": str(code)},
            )
            row = _arm(
                cost,
                time.monotonic() - started,
                str(code),
                detail=str(paid)[: self.cfg.limits.eval.ab.log_tail_chars],
            )
            if isinstance(paid, STOPS):
                row["raise"] = paid
            return row

    # ---------------------------------------------------------------- the run
    def _preflight(self, names: Sequence[str]) -> None:
        missing = [n for n in names if not (self.fixtures / n).is_dir()]
        if missing:
            raise PreflightError(f"fixture folders missing: {missing}")
        first = select_inputs(self.fixtures / names[0], self.cfg.limits.eval.ab.max_files)
        problem = self.kit.check(first)
        if problem is not None:
            raise PreflightError(problem)

    def _fits(self, cap: Decimal) -> bool:
        ab_cfg = self.cfg.limits.eval.ab
        return self.spent + cap + ab_cfg.judge_reserve_usd <= ab_cfg.budget_usd

    def run(self) -> Path:
        ab_cfg = self.cfg.limits.eval.ab
        day = self.ports.clock.now().date().isoformat()
        unknown = [n for n in (*self.only, *self.redo) if n not in ab_cfg.fixtures]
        if unknown:
            raise PreflightError(f"not A/B fixtures: {unknown}; see limits.toml [eval.ab]")
        names = [n for n in ab_cfg.fixtures if not self.only or n in self.only]
        self._preflight(names)
        self._load(day)
        caps = {
            "new": evaluate.for_eval(self.cfg, "sonnet").limits.editor.cost_cap_usd,
            "old": ab_cfg.kit_run_cap_usd,
        }
        stopped: str | None = None
        for name in names:
            row = next((r for r in self.rows if r["name"] == name), None)
            if row is None:
                row = {"name": name}
                self.rows.append(row)
            files = select_inputs(self.fixtures / name, ab_cfg.max_files)
            row["files"] = [f.name for f in files]
            base = self.root / OUT / day / name
            for side in SIDES:
                if side in row and row[side]["error"] is None and name not in self.redo:
                    continue  # finished on an earlier run
                if not self._fits(caps[side]):
                    stopped = f"budget: ${self.spent} spent, a {side} run could take ${caps[side]}"
                    break
                previous = row.get(side)
                if previous is not None and previous["error"] is None:
                    row.setdefault("attempts", []).append({"side": side, **previous})
                carried = previous is not None and previous.get("carried")
                # a failed try in this file stays paid in this arm; a carried one was paid elsewhere
                earlier = (
                    Decimal(str(previous["cost_usd"])) if previous and not carried else Decimal(0)
                )
                attempt = base / f"{side}-{self.ports.clock.now():%H%M%S}"
                row[side] = _arm(earlier + caps[side], 0.0, "started")  # if killed, counted at cap
                self._write(day, stopped)
                arm_call = (
                    partial(self._new, files, base, attempt)
                    if side == "new"
                    else partial(self._old, name, files, attempt)
                )
                arm = self._contained(attempt, arm_call)
                raised = arm.pop("raise", None)
                arm["cost_usd"] = float(
                    Decimal(str(arm["cost_usd"])) + earlier
                )  # failed tries stay paid
                self.spent += Decimal(str(arm["cost_usd"])) - earlier
                row[side] = arm
                target = self._write(day, stopped)
                if raised is not None:
                    raise raised
            if stopped is not None:
                break
        target = self._write(day, stopped)
        log.info("ab runs written", extra={"stage": STAGE, "event": "runs", "outcome": stopped})
        return target


class _ArmFailed(Exception):
    """A judge failure after the kit was paid: carries the kit's cost to the record."""

    def __init__(self, cost: Decimal) -> None:
        super().__init__(f"failed after ${cost}")
        self.cost = cost


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make ab", description=__doc__)
    parser.add_argument("--only", default="", help="comma-separated fixture names to (re)run")
    parser.add_argument("--redo", default="", help="fixtures whose finished arms run again")
    args = parser.parse_args(argv)
    configure()
    cfg, settings, build = config.load(), EditorSettings(), BuildSettings()
    media = config.load_media()
    ffmpeg = Ffmpeg(settings.ffmpeg_path, settings.ffprobe_path, media.tools)
    ports, ab_cfg = evaluate.connect_ports(settings, cfg), cfg.limits.eval.ab
    harness = Harness(
        cfg=cfg,
        fixtures=build.reel_fixtures_dir,
        root=evaluate.ROOT,
        ports=ports,
        steps_for=lambda folder: make.media_steps(folder, ffmpeg, media, cfg),
        kit=ab_kit.OldKit(
            build.old_kit_dir, cfg.limits.editor.model, ab_cfg.kit_timeout_s, ab_cfg.log_tail_chars
        ),
        judge=ab_judge.CriticJudge(ports, cfg, media, ffmpeg, order_for(cfg)),
        only=tuple(n for n in args.only.split(",") if n),
        redo=tuple(n for n in args.redo.split(",") if n),
    )
    target = harness.run()
    sys.stdout.write(f"A/B runs: {target} (ledger ${harness.spent}); next: make ab-pick\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
