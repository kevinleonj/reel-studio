"""The old kit's own command, run as a separate process for the A/B (STEP-04; never imported, D30).

`make_reel.py` takes the files, a name and a context line, reads its key from its own .env (F01:
the end user is Kevin) and its cap from REEL_MAX_BUDGET_USD. Its questions read EOF from stdin,
which the kit answers with "decide for me". The run's cost is the last ResultMessage in
runs/<job>.jsonl; a run that wrote none is counted at its cap, so the budget never undercounts.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from reel_studio.core import constants
from reel_studio.core.logging import get_logger
from reel_studio.editor import prompt

log = get_logger(__name__)

STAGE = "ab"
JOB_LINE = re.compile(r"^\[reel\] Job (?P<job>\S+):", re.M)
DRY_RUN_OK = "Setup: OK"
RESULT_TYPE = "ResultMessage"
SUCCESS = "success"


@dataclass(frozen=True)
class KitRun:
    job: str
    cost_usd: Decimal
    wall_s: float
    text: Path | None
    clean: Path | None
    timeline: Path | None
    error: str | None


class Kit(Protocol):
    def check(self, files: list[Path]) -> str | None: ...  # None when the kit is ready
    def run(self, name: str, files: list[Path], cap: Decimal, context: str) -> KitRun: ...


def context_for(order: prompt.OrderSettings, language: str) -> str:
    """The order as the kit's --context line, so both engines edit to the same brief."""
    voice = "Keep the voice." if order.voice else "Voice off: natural sound only."
    return f"Target length {order.length_s} s. On-screen text in {language}. {voice}"


def _result(log_path: Path) -> dict[str, Any] | None:  # Any: one Agent SDK message as JSON
    if not log_path.is_file():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        record: dict[str, Any] = json.loads(line)  # Any: as above
        if record.get("type") == RESULT_TYPE:
            return record
    return None


def kit_cost(log_path: Path) -> Decimal:
    """total_cost_usd of the run's last ResultMessage (kit runs/<job>.jsonl)."""
    result = _result(log_path)
    if result is None or result.get("total_cost_usd") is None:
        raise ValueError(f"no result message in {log_path}")
    return Decimal(str(result["total_cost_usd"]))


@dataclass(frozen=True)
class OldKit:
    root: Path
    model: str
    timeout_s: int
    tail_chars: int  # of the kit's output or result text kept in an error

    def _command(self, *args: str, cap: Decimal | None = None) -> list[str]:
        env = shutil.which("env")  # sets the kit's two variables; the rest is inherited
        if env is None:
            raise FileNotFoundError("env not found on PATH")
        settings = [f"REEL_MODEL={self.model}"]
        if cap is not None:
            settings.append(f"REEL_MAX_BUDGET_USD={cap}")
        python, script = self.root / ".venv" / "bin" / "python", self.root / "make_reel.py"
        return [env, *settings, str(python), str(script), *args]

    def _call(self, command: list[str]) -> tuple[int | None, str, float]:
        """Run in its own process group, so a timeout also stops the CLI and ffmpeg under it."""
        started = time.monotonic()
        with subprocess.Popen(  # noqa: S603 - a fixed command list, no shell
            command,
            cwd=self.root,
            stdin=subprocess.DEVNULL,  # the kit's questions read EOF: "decide for me"
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        ) as proc:
            try:
                out, _ = proc.communicate(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                out, _ = proc.communicate()
                return None, out, time.monotonic() - started
        return proc.returncode, out, time.monotonic() - started

    def check(self, files: list[Path]) -> str | None:
        python = self.root / ".venv" / "bin" / "python"
        if not python.exists() or not (self.root / "make_reel.py").is_file():
            return f"no kit at {self.root} (.venv/bin/python and make_reel.py)"
        code, out, _ = self._call(self._command("--dry-run", *(str(f) for f in files)))
        return (
            None
            if code == 0 and DRY_RUN_OK in out
            else f"kit dry run failed: {out[-self.tail_chars :]}"
        )

    def run(self, name: str, files: list[Path], cap: Decimal, context: str) -> KitRun:
        args = [*(str(f) for f in files), "--name", name, "--context", context]
        code, out, wall = self._call(self._command(*args, cap=cap))
        log.info(
            "kit %s exited %s",
            name,
            code,
            extra={"stage": STAGE, "event": "kit", "latency_ms": round(wall * constants.MS_PER_S)},
        )
        found = JOB_LINE.search(out)
        if found is None:  # it stopped before starting a job: nothing was spent
            return KitRun(
                name, Decimal(0), wall, None, None, None, f"no job: {out[-self.tail_chars :]}"
            )
        job = found["job"]
        result = _result(self.root / "runs" / f"{job}.jsonl")
        cost = cap if result is None else Decimal(str(result.get("total_cost_usd", cap)))
        out_dir = self.root / "output" / job
        text, clean = out_dir / f"{job}_text.mp4", out_dir / f"{job}_clean.mp4"
        timeline = self.root / "work" / job / "review" / f"{job}.timeline.json"
        missing = [p.name for p in (text, clean, timeline) if not p.is_file()]
        error = None
        if result is None or result.get("subtype") != SUCCESS or missing or code is None:
            said = str(result.get("result", "")) if result is not None else out
            kind = result.get("subtype") if result is not None else "no result message"
            timed_out = " timed out" if code is None else ""
            error = f"kit {kind}{timed_out}, missing {missing}: {said[: self.tail_chars]}"
        return KitRun(job, cost, wall, text, clean, timeline, error)
