"""`make ab` (STEP-04, docs/EDITOR.md §11): the new engine against the old kit on the same files.

For each fixture in limits.toml [eval.ab] both engines get the same files (the kit takes at most
15, videos first). The new engine runs `make` with Sonnet; the old kit runs its own make_reel.py
in its own virtual environment (never imported here, D30). Our critic judges both outputs, so the
comparison does not rest on either engine's own critic. The harness stops before a run that could
take the spend past the step budget. It writes eval/results/<date>/ab-runs.json; `make ab-pick`
adds Kevin's blind picks and writes ab.json, the file the step04 gate reads.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from reel_studio.core import config, constants
from reel_studio.core.config import Config
from reel_studio.core.errors import ReelError
from reel_studio.core.logging import configure, get_logger
from reel_studio.core.media_config import Media
from reel_studio.editor import critic, evaluate, loop, make, prompt
from reel_studio.editor.media import qa, render
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.editor.meter import Meter
from reel_studio.settings import BuildSettings, EditorSettings

log = get_logger(__name__)

STAGE = "ab"
RUNS_JSON = "ab-runs.json"
OUT = Path("out") / "ab"
VIDEO_EXT = {ext.lower() for ext in constants.VIDEO_EXT}
JOB_LINE = re.compile(r"^\[reel\] Job (?P<job>\S+):", re.M)
RESULT_TYPE = "ResultMessage"


@dataclass(frozen=True)
class KitRun:
    job: str
    cost_usd: Decimal
    wall_s: float
    text: Path | None
    clean: Path | None
    timeline: Path | None
    error: str | None


@dataclass(frozen=True)
class Judged:
    total: int
    passed: bool
    cost_usd: Decimal
    weakness: str | None


class Kit(Protocol):
    def run(self, name: str, files: list[Path], cap: Decimal) -> KitRun: ...


def select_inputs(folder: Path, max_files: int) -> list[Path]:
    """The files both engines get: videos first, then photos, each by name, at most max_files."""
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    others = [p for p in files if p.suffix.lower() not in VIDEO_EXT]
    return (videos + others)[:max_files]


def stage(files: list[Path], folder: Path) -> Path:
    """A folder of links to `files`, so `make` reads exactly them and the fixture stays as it is."""
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        link = folder / f.name
        if not link.exists():
            link.symlink_to(f.resolve())
    return folder


def kit_cost(log_path: Path) -> Decimal:
    """total_cost_usd of the run's last ResultMessage (kit runs/<job>.jsonl)."""
    lines = log_path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        record: dict[str, Any] = json.loads(line)  # Any: one Agent SDK message as JSON
        if record.get("type") == RESULT_TYPE and record.get("total_cost_usd") is not None:
            return Decimal(str(record["total_cost_usd"]))
    raise ValueError(f"no result message in {log_path}")


@dataclass(frozen=True)
class OldKit:
    """The old kit's own command (STEP-04: run with Kevin's key in its own .env, F01)."""

    root: Path
    model: str
    timeout_s: int
    tail_chars: int  # of the kit's output kept when it names no job

    def run(self, name: str, files: list[Path], cap: Decimal) -> KitRun:
        env = shutil.which("env")  # sets the kit's two variables; the rest is inherited
        if env is None:
            raise FileNotFoundError("env not found on PATH")
        command = [
            env,
            f"REEL_MAX_BUDGET_USD={cap}",
            f"REEL_MODEL={self.model}",
            str(self.root / ".venv" / "bin" / "python"),
            str(self.root / "make_reel.py"),
            *(str(f) for f in files),
            "--name",
            name,
        ]
        started = time.monotonic()
        done = subprocess.run(  # noqa: S603 - a fixed command list, no shell
            command,
            cwd=self.root,
            stdin=subprocess.DEVNULL,  # the kit's questions read EOF: "decide for me"
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            check=False,
        )
        wall = time.monotonic() - started
        found = JOB_LINE.search(done.stdout)
        log.info(
            "kit %s exited %d",
            name,
            done.returncode,
            extra={"stage": STAGE, "event": "kit", "latency_ms": round(wall * constants.MS_PER_S)},
        )
        if found is None:
            return KitRun(
                name,
                Decimal(0),
                wall,
                None,
                None,
                None,
                f"no job: {done.stdout[-self.tail_chars :]}",
            )
        job = found["job"]
        cost = kit_cost(self.root / "runs" / f"{job}.jsonl")
        out = self.root / "output" / job
        text, clean = out / f"{job}_text.mp4", out / f"{job}_clean.mp4"
        timeline = self.root / "work" / job / "review" / f"{job}.timeline.json"
        missing = [p.name for p in (text, clean, timeline) if not p.is_file()]
        error = f"kit exit {done.returncode}, missing {missing}" if missing else None
        return KitRun(job, cost, wall, text, clean, timeline, error)


@dataclass(frozen=True)
class CriticJudge:
    """Our critic on the kit's output: our QA sheets and lines from the kit's timeline."""

    ports: make.Ports
    cfg: Config
    media: Media
    ffmpeg: Ffmpeg

    def __call__(self, run: KitRun, folder: Path) -> Judged:
        if run.text is None or run.clean is None or run.timeline is None:
            raise ValueError(f"kit run {run.job} has no output to judge")
        out = folder / "out"
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run.text, out / render.TEXT)
        shutil.copy2(run.clean, out / render.CLEAN)
        timeline = render.Timeline.model_validate_json(run.timeline.read_text(encoding="utf-8"))
        job = render.Job(folder / make.WORK, None, out, self.ffmpeg, self.media)
        side = self.cfg.limits.sheets.max_image_side_px
        result = qa.run(job, timeline, side)
        editor = self.cfg.limits.editor
        meter = Meter(self.cfg.prices, editor.cost_cap_usd)
        session = loop.Session(
            self.ports.claude, meter, self.ports.clock, folder / make.REQUESTS, editor, "critic"
        )
        order = prompt.OrderSettings(self.cfg.limits.eval.ab.style, 0, "", False)
        material = critic.Material(
            sheets=[Path(s) for s in result.sheets],
            qa_lines=result.lines,
            timeline=make.timeline_lines(timeline),
            order=make.order_line(order),
        )
        quality = self.media.contact_sheet.jpeg_quality
        review = critic.critique(session, prompt.critic_prompt(self.cfg), material, side, quality)
        ok, why = critic.passes(review, self.cfg.limits.gates)
        return Judged(review.total, ok, meter.spent, why if not ok else None)


def _arm(total: int, passed: bool, cost: Decimal, wall: float, **rest: object) -> dict[str, Any]:
    # Any: JSON; cost exact as a number with far fewer than 15 digits
    return {
        "critic_total": total,
        "passed": passed,
        "cost_usd": float(cost),
        "wall_s": wall,
        **rest,
    }


@dataclass
class Harness:
    cfg: Config
    fixtures: Path  # REEL_FIXTURES_DIR
    root: Path  # the repository
    ports: make.Ports
    steps_for: Callable[[Path], make.Steps]  # the render reads style photos from the folder
    kit: Kit
    judge_old: Callable[[KitRun, Path], Judged]
    spent: Decimal = Decimal(0)

    def _fits(self, cap: Decimal) -> bool:
        return self.spent + cap <= self.cfg.limits.eval.ab.budget_usd

    def _new(self, name: str, folder: Path, base: Path) -> dict[str, Any]:  # Any: JSON
        chosen = evaluate.for_eval(self.cfg, "sonnet")
        out, ab_cfg = base / "new", self.cfg.limits.eval.ab
        order = prompt.OrderSettings(
            ab_cfg.style,
            self.cfg.limits.order.default_length_s,
            self.cfg.styles.text_languages.items[0].code,
            False,  # transcription arrives in STEP-05
        )
        started = time.monotonic()
        try:
            request = make.Request(folder, out, order)
            made = make.make(request, self.ports, self.steps_for(folder), chosen)
        except ReelError as exc:
            _, _, cost = evaluate.calls_of(out / make.REQUESTS)
            self.spent += cost
            wall = time.monotonic() - started
            return _arm(0, False, cost, wall, error=str(exc.code), outputs={})
        self.spent += made.cost
        review = made.final.review
        return _arm(
            review.total if review is not None else 0,
            made.final.passed,
            made.cost,
            round(time.monotonic() - started, 1),
            weakness=made.final.weakness,
            outputs={"text": str((out / render.TEXT).relative_to(self.root))},
        )

    def _old(self, name: str, files: list[Path], base: Path) -> dict[str, Any]:  # Any: JSON
        ab_cfg = self.cfg.limits.eval.ab
        run = self.kit.run(f"ab{name}", files, ab_cfg.kit_run_cap_usd)
        self.spent += run.cost_usd
        if run.error is not None:
            return _arm(0, False, run.cost_usd, run.wall_s, error=run.error, job=run.job)
        judged = self.judge_old(run, base / "old")
        self.spent += judged.cost_usd
        cost = run.cost_usd + judged.cost_usd
        outputs = {"text": str(run.text)} if run.text is not None else {}
        return _arm(
            judged.total,
            judged.passed,
            cost,
            round(run.wall_s, 1),
            weakness=judged.weakness,
            outputs=outputs,
            job=run.job,
            kit_cost_usd=float(run.cost_usd),
            judge_cost_usd=float(judged.cost_usd),
        )

    def run(self) -> Path:
        ab_cfg, now = self.cfg.limits.eval.ab, self.ports.clock.now()
        day = now.date().isoformat()
        rows: list[dict[str, Any]] = []  # Any: JSON
        stopped: str | None = None
        for name in ab_cfg.fixtures:
            base = self.root / OUT / day / name
            files = select_inputs(self.fixtures / name, ab_cfg.max_files)
            row: dict[str, Any] = {"name": name, "files": [f.name for f in files]}  # Any: JSON
            new_cap = min(self.cfg.limits.eval.run_cap_usd, self.cfg.limits.editor.cost_cap_usd)
            if not self._fits(new_cap):
                stopped = f"budget: ${self.spent} spent, next new run could take ${new_cap}"
                break
            row["new"] = self._new(name, stage(files, base / "inputs"), base)
            if not self._fits(ab_cfg.kit_run_cap_usd):
                cap = ab_cfg.kit_run_cap_usd
                stopped = f"budget: ${self.spent} spent, next kit run could take ${cap}"
                rows.append(row)
                break
            row["old"] = self._old(name, files, base)
            rows.append(row)
        record = {"started": now.isoformat(), "spent_usd": float(self.spent), "stopped": stopped}
        target = self.root / evaluate.RESULTS / day / RUNS_JSON
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({**record, "fixtures": rows}, indent=1) + "\n", "utf-8")
        log.info("ab runs written", extra={"stage": STAGE, "event": "runs", "outcome": stopped})
        return target


def main() -> int:
    configure()
    cfg, settings, build = config.load(), EditorSettings(), BuildSettings()
    media = config.load_media()
    ffmpeg = Ffmpeg(settings.ffmpeg_path, settings.ffprobe_path, media.tools)
    ports = evaluate.connect_ports(settings, cfg)
    harness = Harness(
        cfg=cfg,
        fixtures=build.reel_fixtures_dir,
        root=evaluate.ROOT,
        ports=ports,
        steps_for=lambda folder: make.media_steps(folder, ffmpeg, media, cfg),
        kit=OldKit(
            build.old_kit_dir,
            cfg.limits.editor.model,
            cfg.limits.eval.ab.kit_timeout_s,
            cfg.limits.eval.ab.log_tail_chars,
        ),
        judge_old=CriticJudge(ports, cfg, media, ffmpeg),
    )
    target = harness.run()
    sys.stdout.write(f"A/B runs: {target} (spent ${harness.spent}); next: make ab-pick\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
