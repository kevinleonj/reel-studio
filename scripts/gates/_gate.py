#!/usr/bin/env python3
"""Shared engine of the build-step gates: scripts/gates/stepNN.py.

A gate decides, with no judgement, whether a build step in docs/build/ is finished.

    python3 scripts/gates/stepNN.py [--local]     one step's gate; --local skips GitHub
    python3 scripts/gates/_gate.py --self-test    prove this engine in throwaway repos

Output: one line per check, `ok    <name>` or `FAIL  <name>: <reason>`; a failed command
adds the last 15 lines of its output, indented. Under --local each GitHub check prints
`skip  <name>: --local`. The last line is `GATE stepNN PASS` or
`GATE stepNN FAIL (<k> of <n> checks failed)`. Exit 0 on PASS, 1 on FAIL, 2 when the
gate itself cannot run: bad arguments, no repository, or a bug in this file (shown as a
FAIL line, never as a traceback).

Every gate adds the five common checks (common_checks). Run order: file and git reads
first (fast, and they see the tree as the session left it), the literal scan, `make ci`,
the step's commands, then GitHub.

Kept on purpose:
- Python 3.9+ standard library only: a Mac's /usr/bin/python3 is 3.9 (no tomllib, no
  `match`, no runtime `X | Y`). No sed, readlink, stat, date, timeout or sha256sum,
  whose BSD and GNU forms differ: hashlib hashes, time.monotonic times.
- The repository is never modified: temporary work goes in tempfile.mkdtemp() and is
  deleted, git runs with --no-optional-locks, uv with --locked, Python writes no
  bytecode.
- No environment value and no .env line is printed, except SITE_URL in step 08. Text
  shaped like a key, or equal to a secret-named variable, prints as [redacted].
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TextIO

TIMEOUT = 2 * 60  # every command not named below
TIMEOUT_RENDER = 10 * 60  # fixture clips and reel render
TIMEOUT_LONG = 30 * 60  # make ci and make prerelease
TAIL = 15  # lines of a failed command's output
INDENT = " " * 6
OK, FAIL, SKIP = "ok", "FAIL", "skip"
READ, SCAN, CI, RUN, GITHUB = 0, 1, 2, 3, 4  # check phases, in run order

UV = ("uv", "run", "--locked")  # a stale uv.lock fails here instead of being rewritten
SCANNER = ("python", "scripts/check_literals.py")  # needs Python 3.12+ (tomllib)
LITERAL_SCAN = ("uv", "run", "--quiet", "--no-project", "--python", "3.13", *SCANNER)
AGENT_SDK = ("claude_agent_sdk", "claude-agent-sdk", "tool_runner")
AGENT_SDK_PLACES = ("reel_studio", "pyproject.toml", "uv.lock")
SKIP_DIRS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
RESULTS = "eval/results"
ORIGIN_MAIN = "refs/remotes/origin/main"
PR_FIELDS = "number,state,headRefOid,statusCheckRollup"
MAX_BODY = 5 * 1024 * 1024

DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RESULT_FILE = re.compile(r"^(?P<fixture>.+)-(?P<model>sonnet|haiku)\.json$")
LANE_WORD = re.compile(r"^[A-Za-z0-9_-]+$")
PASSED = re.compile(r"(\d+) passed")
LOUDNESS = re.compile(r"(?<![A-Za-z])I:\s*(\S+)\s+LUFS")
USES = re.compile(r"^\s*(?:-\s+)?uses\s*:\s*(.*)$")
PINNED = re.compile(r"^[^@\s]+@[0-9a-fA-F]{40}$")
DISALLOW = re.compile(r"^\s*disallow\s*:\s*(\S*)", re.IGNORECASE)
LIST_MARK = re.compile(r"^\s*(?:[-*+]\s+)?")
SITE_URL_LINE = re.compile(r"^\s*(?:export\s+)?SITE_URL\s*=\s*(.*?)\s*$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
KEY_SHAPES = (
    r"sk-ant-[A-Za-z0-9_\-]{8,}",  # Anthropic
    r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{8,}",  # Stripe secret, restricted
    r"\bwhsec_[A-Za-z0-9+/=]{8,}",  # Stripe webhook signing secret
    r"\bAIza[0-9A-Za-z_\-]{30,}",  # Google API (Gemini)
    r"\bre_[A-Za-z0-9_]{16,}",  # Resend
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",  # GitHub
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",  # GitHub fine-grained
    r"\bya29\.[0-9A-Za-z_\-]{20,}",  # Google OAuth access
)
SECRET_SHAPES = re.compile("|".join(KEY_SHAPES))


# ------------------------------------------------------------------ results and checks


class Result:
    """One output line: a check that passed, failed or was skipped."""

    __slots__ = ("detail", "name", "status", "tail")

    def __init__(self, status: str, name: str, detail: str = "", tail: Sequence[str] = ()) -> None:
        self.status = status
        self.name = name
        self.detail = detail
        self.tail = list(tail)


def ok_result(name: str, detail: str = "") -> Result:
    return Result(OK, name, detail)


def fail_result(name: str, reason: str, tail: Sequence[str] = ()) -> Result:
    return Result(FAIL, name, reason, tail)


def verdict(name: str, good: bool, detail: str) -> Result:
    return ok_result(name, detail) if good else fail_result(name, detail)


def not_checked(names: Sequence[str], why: str) -> list[Result]:
    return [fail_result(name, f"not checked: {why}") for name in names]


class Check:
    """Results computed together: `evaluate` returns one Result per name, in order."""

    def __init__(
        self, phase: int, names: Sequence[str], evaluate: Callable[[Ctx], list[Result]]
    ) -> None:
        self.phase = phase
        self.names = list(names)
        self.evaluate = evaluate


class Redactor:
    """Masks text shaped like a key and the values of secret-named variables."""

    def __init__(self, env: dict[str, str]) -> None:
        values = {v for k, v in env.items() if SECRET_NAME.search(k) and len(v) >= 12}
        self.values = sorted(values, key=len, reverse=True)

    def clean(self, text: str) -> str:
        for value in self.values:
            text = text.replace(value, "[redacted]")
        return SECRET_SHAPES.sub("[redacted]", text)


class Report:
    """Prints each check line as it comes and the verdict line at the end."""

    def __init__(self, step: str, out: TextIO, env: dict[str, str]) -> None:
        self.step = step
        self.out = out
        self.redactor = Redactor(env)
        self.total = 0
        self.failed = 0
        self.error = False

    def add(self, result: Result) -> None:
        name, detail = flat(result.name), flat(result.detail)
        if result.status == SKIP:
            self.emit(f"skip  {name}: {detail}")
            return
        self.total += 1
        if result.status == OK:
            self.emit(f"ok    {name} ({detail})" if detail else f"ok    {name}")
            return
        self.failed += 1
        self.emit(f"FAIL  {name}: {detail}")
        for line in result.tail:
            self.emit(INDENT + line)

    def finish(self, error: bool = False) -> int:
        """Print the last line; return the exit code."""
        if self.failed == 0 and not (error or self.error):
            self.emit(f"GATE step{self.step} PASS")
            return 0
        failed = f"{self.failed} of {self.total} checks failed"
        self.emit(f"GATE step{self.step} FAIL ({failed})")
        return 2 if error or self.error else 1

    def emit(self, line: str) -> None:
        try:
            self.out.write(self.redactor.clean(line) + "\n")
            self.out.flush()
        except BrokenPipeError:  # `| head` closed the pipe: finish quietly
            devnull = os.open(os.devnull, os.O_WRONLY)
            with contextlib.suppress(OSError, ValueError):
                os.dup2(devnull, sys.stdout.fileno())


def flat(text: str) -> str:
    """One line: newlines and runs of blanks become single spaces."""
    return " ".join(str(text).split())


# ------------------------------------------------------------------ commands


class Ran:
    """What a command did: its exit code and output, or why it did not finish."""

    def __init__(
        self,
        argv: Sequence[str],
        code: int | None = None,
        out: str = "",
        err: str = "",
        problem: str = "",
        missing: bool = False,
    ) -> None:
        self.argv = list(argv)
        self.code = code
        self.out = out
        self.err = err
        self.problem = problem
        self.missing = missing

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.problem

    def why(self) -> str:
        return self.problem or f"exit {self.code}"

    def tail(self) -> list[str]:
        return last_lines("\n".join(part for part in (self.out, self.err) if part))


def run_command(
    argv: Sequence[str],
    cwd: Path | str,
    env: dict[str, str],
    timeout: float = TIMEOUT,
    split: bool = False,
) -> Ran:
    """Run argv in its own process group; a timeout or Ctrl-C kills the whole group.

    split=False merges stderr into stdout, for output tails; split=True keeps them
    apart, for commands whose stdout is JSON.
    """
    if shutil.which(argv[0], path=env.get("PATH", os.defpath)) is None:
        return Ran(argv, problem=f"{argv[0]}: command not found", missing=True)
    try:
        proc = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if split else subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        return Ran(argv, problem=f"{argv[0]} cannot start ({exc.strerror or exc})")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        out, err = stop_group(proc)
        late = f"timed out after {duration(timeout)}"
        return Ran(argv, proc.returncode, text(out), text(err), problem=late)
    except BaseException:  # Ctrl-C: the group has its own session, so stop it here
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)
        raise
    return Ran(argv, proc.returncode, text(out), text(err))


def stop_group(proc: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    """Kill the command and everything it started, then collect what it printed."""
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired as exc:  # a grandchild left the group, pipe open
        out, err = exc.output, exc.stderr
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
    return out or b"", err or b""


def text(data: bytes | None) -> str:
    return data.decode("utf-8", "replace") if data else ""


def last_lines(output: str, count: int = TAIL) -> list[str]:
    """The last lines as a terminal shows them: no colour codes, no control bytes, and
    only the final state of a line redrawn with carriage returns."""
    lines = []
    for raw in output.replace("\r\n", "\n").split("\n"):
        parts = [part for part in raw.split("\r") if part.strip()]
        line = parts[-1] if parts else ""
        lines.append(CONTROL.sub("", ANSI.sub("", line)).rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return lines[-count:]


def duration(seconds: float) -> str:
    return f"{seconds / 60:g} min" if seconds >= 60 else f"{seconds:g} s"


def shown(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in argv)


def uv(*args: str) -> tuple[str, ...]:
    """A project command through `uv run --locked`."""
    return (*UV, *args)


def strip_ansi(output: str) -> str:
    return ANSI.sub("", output)


def passed_count(output: str) -> int:
    """The number in pytest's last `N passed`, or 0."""
    found = PASSED.findall(strip_ansi(output))
    return int(found[-1]) if found else 0


# ------------------------------------------------------------------ context


class Ctx:
    """What every check sees: the repository root, --local, the command environment."""

    def __init__(self, root: Path, local: bool, env: dict[str, str]) -> None:
        self.root = root
        self.local = local
        self.env = env
        self.memo: dict[str, Any] = {}

    def run(self, argv: Sequence[str], timeout: float = TIMEOUT, split: bool = False) -> Ran:
        return run_command(argv, self.root, self.env, timeout, split)

    def git(self, *args: str) -> Ran:
        """git without optional locks, so a status never rewrites the index."""
        return self.run(("git", "--no-optional-locks", *args), split=True)

    def head(self) -> str | None:
        if "head" not in self.memo:
            ran = self.git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
            self.memo["head"] = ran.out.strip() if ran.ok and ran.out.strip() else None
        return self.memo["head"]

    def merge_base(self) -> tuple[str | None, str]:
        """(merge base of HEAD and origin/main, "") or (None, why)."""
        if "base" not in self.memo:
            self.memo["base"] = self.find_merge_base()
        return self.memo["base"]

    def find_merge_base(self) -> tuple[str | None, str]:
        found = self.git("rev-parse", "--verify", "--quiet", ORIGIN_MAIN + "^{commit}")
        if found.missing:
            return None, found.why()
        if not found.ok:
            return None, "origin/main is missing: fetch origin first (git fetch origin)"
        if self.head() is None:
            return None, "HEAD has no commit yet"
        base = self.git("merge-base", "HEAD", ORIGIN_MAIN)
        if not base.ok or not base.out.strip():
            return None, "HEAD and origin/main share no commit"
        return base.out.strip(), ""

    def changed_on_branch(
        self, *pathspec: str, added_only: bool = False
    ) -> tuple[list[str] | None, str]:
        """Paths changed between the merge base and HEAD, or (None, why)."""
        base, why = self.merge_base()
        if base is None:
            return None, why
        args = ["diff", "--name-only", "--no-renames", "-z"]
        if added_only:
            args.append("--diff-filter=A")
        args += [base, "HEAD", "--", *pathspec]
        ran = self.git(*args)
        if not ran.ok:
            return None, f"git diff: {ran.why()}"
        return [path for path in ran.out.split("\0") if path], ""

    def handoff(self) -> tuple[str | None, str]:
        """HANDOFF.md for lane main (no .lane file), docs/handoff/<lane>.md otherwise."""
        try:
            word = (self.root / ".lane").read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            return "HANDOFF.md", ""
        except (OSError, ValueError) as exc:
            return None, f".lane cannot be read ({exc})"
        if not LANE_WORD.match(word):
            return None, f".lane must hold one lane word, not {show(word)}"
        return ("HANDOFF.md" if word == "main" else f"docs/handoff/{word}.md"), ""


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def short(sha: object) -> str:
    return str(sha)[:12] if sha else "nothing"


def read_text(ctx: Ctx, rel: str) -> tuple[str | None, str]:
    path = ctx.root / rel
    try:
        return path.read_text(encoding="utf-8", errors="replace"), ""
    except FileNotFoundError:
        return None, f"{rel} is missing"
    except IsADirectoryError:
        return None, f"{rel} is a folder"
    except OSError as exc:
        return None, f"{rel} cannot be read ({exc.strerror})"


# ------------------------------------------------------------------ JSON and numbers


def parse_json(data: str) -> tuple[Any, str]:
    """(value, "") or (None, why). Floats become Decimal: sums and caps compare exactly."""
    try:
        return json.loads(data, parse_float=Decimal, parse_constant=refuse_constant), ""
    except ValueError as exc:
        return None, f"not valid JSON ({exc})"


def refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")


def read_json(path: Path) -> tuple[Any, str]:
    try:
        data = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, f"{path.name} is missing"
    except (OSError, ValueError) as exc:
        return None, f"{path.name} cannot be read ({exc})"
    return parse_json(data)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def show(value: Any) -> str:
    """A short JSON-like rendering of a value for a message."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        return str(value)
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    rendered = json.dumps(str(value))
    return rendered if len(rendered) <= 40 else rendered[:37] + '..."'


def money(value: Decimal) -> str:
    """$1.20 when cents are exact, else four decimals ($0.0473)."""
    try:
        cents = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cents == value:
            return f"${cents}"
        return f"${value.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}"
    except InvalidOperation:
        return f"${value}"


def num(value: Decimal) -> str:
    try:
        return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return str(value)


# ------------------------------------------------------------------ the gate


def main(step: str, checks: Sequence[Check]) -> None:
    """Entry point of every step file: python3 scripts/gates/stepNN.py [--local]."""
    quiet_bad_bytes()
    stop_like_ctrl_c()
    sys.exit(run_gate(step, checks, sys.argv[1:], sys.stdout))


def stop_like_ctrl_c() -> None:
    """SIGTERM and SIGHUP stop the gate the way Ctrl-C does. Each command runs in its own
    process group, so this is what kills a running `make ci` instead of orphaning it."""

    def interrupt(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, interrupt)


def quiet_bad_bytes() -> None:
    """A C locale must not crash the gate on a non-ASCII byte in command output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="backslashreplace")


def run_gate(
    step: str,
    checks: Sequence[Check],
    argv: Sequence[str],
    out: TextIO,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Run the common checks and the step's checks; return the exit code."""
    env = dict(os.environ if env is None else env)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    report = Report(step, out, env)
    current = "starting"
    try:
        unknown = [arg for arg in argv if arg != "--local"]
        if unknown:
            usage = f"python3 scripts/gates/step{step}.py [--local]"
            reason = f"unknown {' '.join(unknown)}; usage: {usage}"
            report.add(fail_result("arguments", reason))
            return report.finish(error=True)
        try:
            here = cwd if cwd is not None else os.getcwd()
        except OSError:
            report.add(fail_result("repository root", "the current folder no longer exists"))
            return report.finish(error=True)
        root, problem = find_root(step, here, env)
        if root is None:
            report.add(fail_result("repository root", problem))
            return report.finish(error=True)
        ctx = Ctx(root, "--local" in argv, env)
        ordered = sorted([*common_checks(), *checks], key=lambda check: check.phase)
        for check in ordered:
            current = check.names[0]
            for result in evaluate_check(check, ctx, report):
                report.add(result)
    except KeyboardInterrupt:
        report.add(fail_result(current, "interrupted"))
        return report.finish(error=True)
    except Exception as exc:  # noqa: BLE001 - a bug outside any check is a FAIL line too
        report.add(fail_result(current, gate_bug(exc)))
        return report.finish(error=True)
    return report.finish()


def evaluate_check(check: Check, ctx: Ctx, report: Report) -> list[Result]:
    if ctx.local and check.phase == GITHUB:
        return [Result(SKIP, name, "--local") for name in check.names]
    try:
        return check.evaluate(ctx)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - a bug in a check: say where, go on, exit 2
        report.error = True
        first = fail_result(check.names[0], gate_bug(exc))
        return [first, *not_checked(check.names[1:], "gate error above")]


def gate_bug(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    where = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else "?"
    return f"gate error {type(exc).__name__}: {exc} (at {where}); scripts/gates has a bug"


def find_root(step: str, cwd: str, env: dict[str, str]) -> tuple[Path | None, str]:
    """`git rev-parse --show-toplevel` from cwd, if it holds this step's build doc."""
    ran = run_command(("git", "rev-parse", "--show-toplevel"), cwd, env, split=True)
    if ran.missing:
        return None, ran.why()
    if not ran.ok or not ran.out.strip():
        said = (ran.err.strip().splitlines() or [ran.why()])[0]
        return None, f"not inside a git repository ({said}); run the gate from the repo"
    root = Path(ran.out.strip())
    marker = f"docs/build/STEP-{step}.md"
    if not (root / marker).is_file():
        return None, f"{root} is not the reel-studio repository: {marker} is missing"
    return root, ""


# ------------------------------------------------------------------ common checks


def common_checks() -> list[Check]:
    """The five checks every gate runs (steps 01-09)."""
    return [no_agent_sdk(), handoff_changed(), literal_scan(), make_ci(), pull_request()]


def no_agent_sdk() -> Check:
    words = ", ".join(AGENT_SDK)
    name = f"no Agent SDK ({words}) in reel_studio/, pyproject.toml, uv.lock"

    def evaluate(ctx: Ctx) -> list[Result]:
        hits: list[str] = []
        searched = 0
        for place in AGENT_SDK_PLACES:
            for path in files_under(ctx.root / place):
                searched += 1
                hits += sdk_mentions(path, ctx.root)
        if hits:
            return [fail_result(name, f"{len(hits)} found: " + "; ".join(hits[:5]))]
        return [ok_result(name, f"{searched} files searched")]

    return Check(READ, [name], evaluate)


def files_under(top: Path) -> list[Path]:
    """`top` when it is a file, every file below it when it is a folder, else none."""
    if top.is_file():
        return [top]
    found: list[Path] = []
    for folder, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        keep = sorted(f for f in files if not f.endswith(".pyc") and f != ".DS_Store")
        found += [Path(folder) / f for f in keep]
    return found


def sdk_mentions(path: Path, root: Path) -> list[str]:
    try:
        data = path.read_bytes().lower()
    except OSError as exc:
        return [f"{relpath(path, root)} cannot be read ({exc.strerror})"]
    hits = []
    for word in AGENT_SDK:
        start = data.find(word.encode())
        if start >= 0:
            line = data.count(b"\n", 0, start) + 1
            hits.append(f"{relpath(path, root)}:{line} {word}")
    return hits


def handoff_changed() -> Check:
    label = "handoff file changed on this branch"

    def evaluate(ctx: Ctx) -> list[Result]:
        handoff, why = ctx.handoff()
        if handoff is None:
            return [fail_result(label, why)]
        name = f"{label} ({handoff})"
        changed, why = ctx.changed_on_branch()
        if changed is None:
            return [fail_result(name, why)]
        count = f"{len(changed)} files changed since origin/main"
        if handoff.lower() in {path.lower() for path in changed}:
            return [ok_result(name, count)]
        return [fail_result(name, f"{handoff} is not among the {count}; update and commit it")]

    return Check(READ, [label], evaluate)


def literal_scan() -> Check:
    return command(LITERAL_SCAN, "literal scan (scripts/check_literals.py) exits 0", SCAN)


def make_ci() -> Check:
    name = "make ci exits 0 and .ci-pass equals HEAD"

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(("make", "ci"), TIMEOUT_LONG)
        if not ran.ok:
            return [fail_result(name, f"make ci: {ran.why()}", ran.tail())]
        head = ctx.head()
        if head is None:
            return [fail_result(name, "HEAD has no commit yet")]
        status = ctx.git("status", "--porcelain", "--untracked-files=normal")
        if not status.ok:
            return [fail_result(name, f"git status: {status.why()}", status.tail())]
        dirty = [line.strip() for line in status.out.splitlines() if line.strip()]
        if dirty:
            where = f"git status lists {len(dirty)}, first: {dirty[0]}"
            rule = "make ci writes .ci-pass only on a clean tree"
            fix = "commit or stash, then run the gate again"
            return [fail_result(name, f"the working tree is dirty ({where}): {rule}; {fix}")]
        try:
            stamp: str | None = (ctx.root / ".ci-pass").read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            stamp = None
        if stamp is None:
            return [fail_result(name, ".ci-pass is missing although the tree is clean")]
        if stamp != head:
            return [fail_result(name, f".ci-pass holds {short(stamp)}, HEAD is {short(head)}")]
        return [ok_result(name, f"HEAD {short(head)}")]

    return Check(CI, [name], evaluate)


def pull_request() -> Check:
    name = "pull request open or merged, every status check SUCCESS"

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(("gh", "pr", "view", "--json", PR_FIELDS), split=True)
        if not ran.ok:
            return [fail_result(name, f"gh pr view: {ran.why()}", ran.tail())]
        data, why = parse_json(ran.out)
        if why:
            return [fail_result(name, f"gh pr view printed {why}")]
        good, detail = pr_verdict(data, ctx.head())
        return [verdict(name, good, detail)]

    return Check(GITHUB, [name], evaluate)


def pr_verdict(data: Any, head: str | None) -> tuple[bool, str]:
    """OPEN or MERGED, its head is local HEAD, every status check succeeded."""
    if not isinstance(data, dict):
        return False, "gh pr view did not answer with a JSON object"
    label = f"PR #{data.get('number')} {data.get('state')}"
    if data.get("state") not in ("OPEN", "MERGED"):
        return False, f"{label}: it must be OPEN or MERGED"
    pr_head = data.get("headRefOid")
    if head is not None and pr_head != head:
        heads = f"its head is {short(pr_head)}, local HEAD is {short(head)}"
        return False, f"{label}: {heads}; push or pull until they match"
    rollup = data.get("statusCheckRollup")
    if not rollup:  # gh prints null when the commit has no checks
        return False, f"{label}: no status checks reported yet"
    if not isinstance(rollup, list):
        return False, f"{label}: statusCheckRollup is not a list"
    green, pending, red = 0, [], []
    for entry in rollup:
        state, check = check_state(entry)
        if state == "green":
            green += 1
        elif state == "pending":
            pending.append(check)
        else:
            red.append(check)
    if red:
        running = f"; CI still running: {', '.join(pending)}" if pending else ""
        return False, f"{label}: failed: {', '.join(red)}{running}"
    if pending:
        return False, f"{label}: CI still running: {', '.join(pending)}"
    return True, f"{label}, {green} checks SUCCESS"


def check_state(entry: Any) -> tuple[str, str]:
    """("green" | "pending" | "red", label) for one statusCheckRollup entry."""
    if not isinstance(entry, dict):
        return "red", "an unreadable entry"
    context = entry.get("__typename") == "StatusContext" or (
        "context" in entry and "name" not in entry
    )
    if context:
        label, state = str(entry.get("context") or "?"), str(entry.get("state") or "")
        if state == "SUCCESS":
            return "green", label
        if state in ("PENDING", "EXPECTED", ""):
            return "pending", label
        return "red", f"{label} {state}"
    label = str(entry.get("name") or "?")
    conclusion = str(entry.get("conclusion") or "")
    status = str(entry.get("status") or "")
    if conclusion == "SUCCESS":
        return "green", label
    if status != "COMPLETED" or not conclusion:
        return "pending", label
    return "red", f"{label} {conclusion}"


# ------------------------------------------------------------------ file checks


def exists(*paths: str) -> Check:
    name = f"{paths[0]} exists" if len(paths) == 1 else f"{len(paths)} required files exist"

    def evaluate(ctx: Ctx) -> list[Result]:
        missing = [path for path in paths if not (ctx.root / path).is_file()]
        if missing:
            listed = ", ".join(missing)
            return [fail_result(name, f"missing {len(missing)} of {len(paths)}: {listed}")]
        return [ok_result(name)]

    return Check(READ, [name], evaluate)


def contains(rel: str, *needles: str) -> Check:
    name = f"{rel} contains " + ", ".join(f"'{needle}'" for needle in needles)

    def evaluate(ctx: Ctx) -> list[Result]:
        body, why = read_text(ctx, rel)
        if body is None:
            return [fail_result(name, why)]
        lacking = [f"'{needle}'" for needle in needles if needle not in body]
        if lacking:
            return [fail_result(name, "lacks " + ", ".join(lacking))]
        return [ok_result(name)]

    return Check(READ, [name], evaluate)


def has_lines(rel: str, *lines: str) -> Check:
    name = f"{rel} has the lines " + " ".join(lines)

    def evaluate(ctx: Ctx) -> list[Result]:
        body, why = read_text(ctx, rel)
        if body is None:
            return [fail_result(name, why)]
        present = {line.strip() for line in body.splitlines()}
        lacking = [line for line in lines if line not in present]
        if lacking:
            return [fail_result(name, "missing lines: " + " ".join(lacking))]
        return [ok_result(name)]

    return Check(READ, [name], evaluate)


def line_starting(rel: str, prefix: str) -> Check:
    """A line starting with `prefix`; a leading Markdown list mark ('- ') is allowed."""
    name = f"{rel} has a line starting with '{prefix}'"

    def evaluate(ctx: Ctx) -> list[Result]:
        body, why = read_text(ctx, rel)
        if body is None:
            return [fail_result(name, why)]
        for line in body.splitlines():
            content = LIST_MARK.sub("", line, count=1)
            if content.startswith(prefix):
                seen = content if len(content) <= 80 else content[:77] + "..."
                return [ok_result(name, seen)]
        return [fail_result(name, f"no such line in {rel} (a leading '- ' is allowed)")]

    return Check(READ, [name], evaluate)


def workflows(*expected: str) -> Check:
    want = sorted(expected)
    name = ".github/workflows/ holds exactly " + " and ".join(want)

    def evaluate(ctx: Ctx) -> list[Result]:
        folder = ctx.root / ".github" / "workflows"
        try:
            found = sorted(e for e in os.listdir(folder) if e != ".DS_Store")
        except FileNotFoundError:
            return [fail_result(name, ".github/workflows/ is missing")]
        except OSError as exc:
            return [fail_result(name, f".github/workflows/ cannot be read ({exc.strerror})")]
        if found != want:
            return [fail_result(name, "found " + (", ".join(found) or "nothing"))]
        return [ok_result(name)]

    return Check(READ, [name], evaluate)


def actions_pinned(rel: str) -> Check:
    name = f"{rel} pins every uses: to a 40-character commit SHA"

    def evaluate(ctx: Ctx) -> list[Result]:
        body, why = read_text(ctx, rel)
        if body is None:
            return [fail_result(name, why)]
        refs = []
        for line in body.splitlines():
            match = USES.match(line)
            if match:
                refs.append(match.group(1).split("#", 1)[0].strip().strip("'\""))
        loose = [ref for ref in refs if not PINNED.match(ref)]
        if loose:
            return [fail_result(name, "not pinned: " + ", ".join(loose[:5]))]
        return [ok_result(name, f"{len(refs)} uses: lines")]

    return Check(READ, [name], evaluate)


# ------------------------------------------------------------------ command checks


def command(
    argv: Sequence[str], name: str | None = None, phase: int = RUN, timeout: float = TIMEOUT
) -> Check:
    label = name if name is not None else f"{shown(argv)} exits 0"

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(argv, timeout)
        return [ok_result(label)] if ran.ok else [fail_result(label, ran.why(), ran.tail())]

    return Check(phase, [label], evaluate)


def output_has(argv: Sequence[str], *needles: str) -> Check:
    quoted = ", ".join(f"'{needle}'" for needle in needles)
    name = f"{shown(argv)} exits 0 and prints {quoted}"

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(argv)
        if not ran.ok:
            return [fail_result(name, ran.why(), ran.tail())]
        output = strip_ansi(ran.out)
        lacking = [f"'{needle}'" for needle in needles if needle not in output]
        if lacking:
            return [fail_result(name, "output lacks " + ", ".join(lacking), ran.tail())]
        return [ok_result(name)]

    return Check(RUN, [name], evaluate)


def pytest_markers(*markers: str) -> Check:
    argv = uv("pytest", "--markers", "-p", "no:cacheprovider")
    name = f"{shown(argv)} lists the markers " + ", ".join(markers)

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(argv)
        if not ran.ok:
            return [fail_result(name, ran.why(), ran.tail())]
        output = strip_ansi(ran.out)
        lacking = [
            marker
            for marker in markers
            if not re.search(rf"@pytest\.mark\.{re.escape(marker)}\b[^:\n]*:", output)
        ]
        if lacking:
            return [fail_result(name, "not registered: " + ", ".join(lacking))]
        return [ok_result(name)]

    return Check(RUN, [name], evaluate)


def pytest_passed(args: Sequence[str], minimum: int) -> Check:
    argv = uv("pytest", "-q", "-p", "no:cacheprovider", *args)
    name = f"{shown(argv)} exits 0 with at least {minimum} passed"

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(argv)
        if not ran.ok:
            return [fail_result(name, ran.why(), ran.tail())]
        count = passed_count(ran.out)
        if count < minimum:
            return [fail_result(name, f"{count} passed", ran.tail())]
        return [ok_result(name, f"{count} passed")]

    return Check(RUN, [name], evaluate)


def ruleset() -> Check:
    argv = ("gh", "api", "repos/{owner}/{repo}/rulesets")
    name = f"{shown(argv)} lists at least one ruleset"

    def evaluate(ctx: Ctx) -> list[Result]:
        ran = ctx.run(argv, split=True)
        if not ran.ok:
            return [fail_result(name, f"gh api: {ran.why()}", ran.tail())]
        data, why = parse_json(ran.out)
        if why:
            return [fail_result(name, f"gh api printed {why}")]
        if not isinstance(data, list) or not data:
            return [fail_result(name, "the repository has no ruleset")]
        names = [str(item.get("name")) for item in data if isinstance(item, dict)]
        return [ok_result(name, f"{len(data)}: " + ", ".join(names))]

    return Check(GITHUB, [name], evaluate)


# ------------------------------------------------------------------ step 02: render


class Spec:
    """The locked output values a render must meet."""

    def __init__(
        self,
        width: int,
        height: int,
        fps: str,
        video: str,
        audio: str,
        lufs: float,
        tolerance: float,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.video = video
        self.audio = audio
        self.lufs = Decimal(str(lufs))
        self.tolerance = Decimal(str(tolerance))


class TempDir:
    """A folder from tempfile.mkdtemp(), removed on exit whatever happened inside."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.path = Path(os.path.realpath(tempfile.mkdtemp(prefix=self.prefix)))
        return self.path

    def __exit__(self, *exc_info: object) -> None:
        if self.path is not None:
            remove_tree(self.path)


def remove_tree(path: Path) -> None:
    """Delete a folder; make read-only folders writable first if a plain delete fails."""
    shutil.rmtree(path, ignore_errors=True)
    if not path.exists():
        return
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
    for folder, dirs, _files in os.walk(path):
        for name in dirs:
            with contextlib.suppress(OSError):
                os.chmod(os.path.join(folder, name), 0o700)
    shutil.rmtree(path, ignore_errors=True)


def render_roundtrip(
    edl: str,
    *,
    min_clips: int,
    width: int,
    height: int,
    fps: str,
    video: str,
    audio: str,
    lufs: float,
    tolerance: float,
) -> Check:
    """make_clips.py into a temp folder, reel render, then input hashes and outputs."""
    spec = Spec(width, height, fps, video, audio, lufs, tolerance)
    outputs = ("text.mp4", "clean.mp4")
    form = f"{width}x{height}, {video}, {fps} fps, {audio} audio, duration > 0"
    level = f"integrated loudness within {tolerance} LU of {lufs} LUFS"
    names = [
        f"fixture clips: tests/fixtures/make_clips.py writes at least {min_clips} files",
        f"reel render --edl {edl} on the fixture clips exits 0",
        "input folder byte-identical after reel render (D02)",
        *[f"{output}: {form}" for output in outputs],
        *[f"{output}: {level}" for output in outputs],
        "qa.json: every value under hard_checks is true",
    ]

    def evaluate(ctx: Ctx) -> list[Result]:
        with TempDir("gate-render-") as tmp:
            return render_results(ctx, tmp, names, edl, min_clips, spec)

    return Check(RUN, names, evaluate)


def render_results(
    ctx: Ctx, tmp: Path, names: Sequence[str], edl: str, min_clips: int, spec: Spec
) -> list[Result]:
    src, dst = tmp / "in", tmp / "out"
    src.mkdir()
    made = ctx.run(uv("python", "tests/fixtures/make_clips.py", str(src)), TIMEOUT_RENDER)
    before = hash_tree(src)
    if not made.ok:
        first = fail_result(names[0], f"make_clips.py: {made.why()}", made.tail())
        return [first, *not_checked(names[1:], "no fixture clips")]
    if len(before) < min_clips:
        first = fail_result(names[0], f"{len(before)} files written")
        return [first, *not_checked(names[1:], "too few fixture clips")]
    results = [ok_result(names[0], f"{len(before)} files")]
    argv = uv("reel", "render", "--edl", edl, str(src), "--out", str(dst))
    render = ctx.run(argv, TIMEOUT_RENDER)
    if render.ok:
        results.append(ok_result(names[1]))
    else:
        results.append(fail_result(names[1], render.why(), render.tail()))
    if render.missing:
        results += not_checked(names[2:3], "reel render did not start")
    else:
        results.append(tree_verdict(names[2], before, hash_tree(src)))
    files = (dst / "text.mp4", dst / "clean.mp4")
    results += [probe_verdict(ctx, n, f, spec) for n, f in zip(names[3:5], files)]
    results += [loudness_verdict(ctx, n, f, spec) for n, f in zip(names[5:7], files)]
    results.append(qa_verdict(names[7], dst / "qa.json"))
    return results


def hash_tree(top: Path) -> dict[str, str]:
    """{relative path: SHA-256} of every file below `top`."""
    found = {}
    for folder, dirs, files in os.walk(top):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(folder, name)
            found[os.path.relpath(full, top).replace(os.sep, "/")] = sha256_file(full)
    return found


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        return f"unreadable ({exc.strerror})"
    return digest.hexdigest()


def tree_verdict(name: str, before: dict[str, str], after: dict[str, str]) -> Result:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    parts = [
        f"{label}: " + ", ".join(paths[:5])
        for label, paths in (("changed", changed), ("added", added), ("removed", removed))
        if paths
    ]
    if parts:
        return fail_result(name, "; ".join(parts))
    return ok_result(name, f"{len(before)} files, SHA-256 equal")


def probe_verdict(ctx: Ctx, name: str, path: Path, spec: Spec) -> Result:
    if not path.is_file():
        return fail_result(name, f"{path.name} is missing from the render output")
    argv = ("ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json")
    ran = ctx.run((*argv, str(path)), split=True)
    if not ran.ok:
        return fail_result(name, f"ffprobe: {ran.why()}", ran.tail())
    data, why = parse_json(ran.out)
    if why:
        return fail_result(name, f"ffprobe printed {why}")
    problems = probe_problems(data, spec)
    if problems:
        return fail_result(name, "; ".join(problems))
    return ok_result(name, f"{data['format']['duration']} s")


def probe_problems(data: Any, spec: Spec) -> list[str]:
    """How an ffprobe -show_streams -show_format JSON answer misses the spec."""
    streams = data.get("streams") if isinstance(data, dict) else None
    if not isinstance(streams, list):
        return ["ffprobe listed no streams"]
    streams = [s for s in streams if isinstance(s, dict)]
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    want = (spec.width, spec.height, spec.video, spec.fps)
    problems = []
    if not videos:
        problems.append("no video stream")
    elif not any(video_form(s) == want for s in videos):
        width, height, codec, rate = video_form(videos[0])
        problems.append(f"video is {width}x{height}, {codec}, {rate} fps")
    if not any(s.get("codec_name") == spec.audio for s in audios):
        codecs = ", ".join(str(s.get("codec_name")) for s in audios) or "none"
        problems.append(f"no {spec.audio} audio stream (audio: {codecs})")
    form = data.get("format") if isinstance(data, dict) else None
    seconds = form.get("duration") if isinstance(form, dict) else None
    try:
        long_enough = Decimal(str(seconds)) > 0
    except (InvalidOperation, ValueError):
        long_enough = False
    if not long_enough:
        problems.append(f"format duration is {show(seconds)}")
    return problems


def video_form(stream: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    get = stream.get
    return get("width"), get("height"), get("codec_name"), get("avg_frame_rate")


def loudness_verdict(ctx: Ctx, name: str, path: Path, spec: Spec) -> Result:
    if not path.is_file():
        return fail_result(name, f"{path.name} is missing from the render output")
    argv = ("ffmpeg", "-hide_banner", "-nostats", "-i", str(path))
    ran = ctx.run((*argv, "-af", "ebur128", "-f", "null", "-"))
    if not ran.ok:
        return fail_result(name, f"ffmpeg ebur128: {ran.why()}", ran.tail())
    value = integrated_loudness(ran.out)
    if value is None:
        return fail_result(name, "no 'I: <value> LUFS' line in the ebur128 output")
    return verdict(name, within(value, spec.lufs, spec.tolerance), f"I: {value} LUFS")


def integrated_loudness(output: str) -> Decimal | None:
    """The value of the last `I: <value> LUFS`: ebur128 prints one per frame, and the
    summary (integrated loudness of the whole file) comes last."""
    found = LOUDNESS.findall(output)
    if not found:
        return None
    try:
        return Decimal(found[-1])
    except InvalidOperation:
        return None


def within(value: Decimal, target: Decimal, tolerance: Decimal) -> bool:
    return value.is_finite() and abs(value - target) <= tolerance


def qa_verdict(name: str, path: Path) -> Result:
    data, why = read_json(path)
    if why:
        return fail_result(name, f"qa.json: {why}")
    if not isinstance(data, dict) or "hard_checks" not in data:
        return fail_result(name, "qa.json has no hard_checks")
    leaves = flatten(data["hard_checks"], "hard_checks")
    bad = [f"{where} = {show(value)}" for where, value in leaves if value is not True]
    if bad:
        return fail_result(name, "; ".join(bad[:6]))
    return ok_result(name, f"{len(leaves)} checks true")


def flatten(value: Any, where: str) -> list[tuple[str, Any]]:
    """Every leaf under value as (path, leaf); an empty object or list is a bad leaf."""
    if isinstance(value, dict):
        if not value:
            return [(where, "empty")]
        pairs = []
        for key in sorted(value):
            pairs += flatten(value[key], f"{where}.{key}")
        return pairs
    if isinstance(value, list):
        if not value:
            return [(where, "empty")]
        pairs = []
        for index, item in enumerate(value):
            pairs += flatten(item, f"{where}[{index}]")
        return pairs
    return [(where, value)]


# ------------------------------------------------------------------ steps 03-05: eval


def date_folders(results: Path) -> list[Path]:
    """eval/results/<YYYY-MM-DD> folders, newest first; any other name is ignored."""
    try:
        names = os.listdir(results)
    except OSError:
        return []
    dated = [n for n in names if DATE_DIR.match(n) and real_date(n)]
    return [results / n for n in sorted(dated, reverse=True) if (results / n).is_dir()]


def real_date(name: str) -> bool:
    try:
        date.fromisoformat(name)
    except ValueError:
        return False
    return True


def newest_with(results: Path, filename: str) -> Path | None:
    for folder in date_folders(results):
        if (folder / filename).is_file():
            return folder / filename
    return None


def eval_problems(data: Any, fixture: str, model: str) -> list[str]:
    """How a make eval result breaks the contract: fixture, model, cost_usd, critic
    {total, passed}, requests [{cache_read_input_tokens}]."""
    if not isinstance(data, dict):
        return ["the top level is not a JSON object"]
    problems = []
    if data.get("fixture") != fixture:
        problems.append(f"fixture is {show(data.get('fixture'))}, the file name says {fixture}")
    if data.get("model") != model:
        problems.append(f"model is {show(data.get('model'))}, the file name says {model}")
    cost = data.get("cost_usd")
    if not is_number(cost) or cost < 0:
        problems.append(f"cost_usd is {show(cost)}, not a number >= 0")
    critic = data.get("critic")
    if not isinstance(critic, dict):
        problems.append("critic is not an object")
    else:
        if not is_number(critic.get("total")):
            problems.append(f"critic.total is {show(critic.get('total'))}, not a number")
        if not isinstance(critic.get("passed"), bool):
            problems.append(f"critic.passed is {show(critic.get('passed'))}, not a bool")
    requests = data.get("requests")
    if not isinstance(requests, list):
        problems.append("requests is not a list")
        return problems
    for index, request in enumerate(requests):
        tokens = request.get("cache_read_input_tokens") if isinstance(request, dict) else None
        if not is_int(tokens) or tokens < 0:
            where = f"requests[{index}].cache_read_input_tokens"
            problems.append(f"{where} is {show(tokens)}, not an integer >= 0")
            break
    return problems


def eval_evidence(fixture: str, *, model: str, max_cost: str, cheaper: str) -> Check:
    """The newest <fixture>-<model>.json meets the cost, critic and cache rules, and a
    <fixture>-<cheaper>.json exists in some date folder."""
    target, other = f"{fixture}-{model}.json", f"{fixture}-{cheaper}.json"
    names = [
        f"eval evidence: newest {RESULTS}/<date>/{target} follows the make eval contract",
        f"{fixture} with {model}: cost_usd <= ${max_cost}",
        f"{fixture} with {model}: critic.passed is true",
        f"{fixture} with {model}: cache_read_input_tokens > 0 from the 2nd request on",
        f"{fixture} with {cheaper}: {RESULTS}/<date>/{other} exists",
    ]

    def evaluate(ctx: Ctx) -> list[Result]:
        results_dir = ctx.root / RESULTS
        path = newest_with(results_dir, target)
        if path is None:
            fix = f"no {RESULTS}/<YYYY-MM-DD>/{target}; run make eval FIX={fixture}"
            results = [fail_result(names[0], fix), *not_checked(names[1:4], "no result")]
        else:
            results = evidence_results(path, ctx.root, names, fixture, model, max_cost)
        found = newest_with(results_dir, other)
        if found is None:
            fix = f"no {RESULTS}/<YYYY-MM-DD>/{other}; run make eval FIX={fixture} MODEL={cheaper}"
            results.append(fail_result(names[4], fix))
        else:
            results.append(ok_result(names[4], relpath(found, ctx.root)))
        return results

    return Check(READ, names, evaluate)


def evidence_results(
    path: Path, root: Path, names: Sequence[str], fixture: str, model: str, max_cost: str
) -> list[Result]:
    rel = relpath(path, root)
    data, why = read_json(path)
    problems = [why] if why else eval_problems(data, fixture, model)
    if problems:
        first = fail_result(names[0], f"{rel}: " + "; ".join(problems))
        return [first, *not_checked(names[1:4], f"{rel} breaks the contract")]
    cost, critic, requests = data["cost_usd"], data["critic"], data["requests"]
    total = f"critic total {critic['total']}"
    results = [
        ok_result(names[0], rel),
        verdict(names[1], cost <= Decimal(max_cost), money(Decimal(cost))),
        verdict(names[2], critic["passed"] is True, total),
    ]
    reads = [request["cache_read_input_tokens"] for request in requests]
    misses = [str(index + 1) for index, tokens in enumerate(reads) if index and tokens <= 0]
    if len(reads) < 2:
        results.append(fail_result(names[3], f"{len(reads)} request(s), need at least 2"))
    elif misses:
        listed = ", ".join(misses)
        results.append(fail_result(names[3], f"0 in request {listed} of {len(reads)}"))
    else:
        later = reads[1:]
        span = f"{len(reads)} requests, later ones read {min(later)}-{max(later)} tokens"
        results.append(ok_result(names[3], span))
    return results


def results_budget(cap: str) -> Check:
    """Sum of cost_usd over eval/results JSON files added on this branch, at HEAD."""
    name = f"paid budget: cost_usd of {RESULTS} files added on this branch <= ${cap}"

    def evaluate(ctx: Ctx) -> list[Result]:
        added, why = ctx.changed_on_branch(RESULTS + "/", added_only=True)
        if added is None:
            return [fail_result(name, why)]
        files = sorted(path for path in added if path.endswith(".json"))
        total, broken = Decimal(0), []
        for rel in files:
            ran = ctx.git("show", f"HEAD:{rel}")
            data, _why = parse_json(ran.out) if ran.ok else (None, ran.why())
            cost = data.get("cost_usd") if isinstance(data, dict) else None
            if is_number(cost) and cost >= 0:
                total += cost
            else:
                broken.append(rel)
        if broken:
            listed = ", ".join(broken[:5])
            return [fail_result(name, f"no cost_usd number >= 0 in {listed}")]
        return [verdict(name, total <= Decimal(cap), f"{money(total)} in {len(files)} files")]

    return Check(READ, [name], evaluate)


def ab_gate(
    *, fixtures: int, min_new_or_tie: int, critic_margin: int, max_mean_cost: str, budget: str
) -> Check:
    """The A/B gate (docs/EDITOR.md section 11), computed from the newest ab.json."""
    names = [
        f"A/B evidence: newest {RESULTS}/<date>/ab.json follows the contract",
        f"A/B picks: new engine picked or tied in >= {min_new_or_tie} of {fixtures}",
        f"A/B critic: mean new critic_total >= mean old - {critic_margin}",
        "A/B gates: no fixture passed by old and failed by new",
        f"A/B cost: mean new cost_usd <= ${max_mean_cost}",
        f"A/B budget: new + old cost_usd <= ${budget}",
    ]

    def evaluate(ctx: Ctx) -> list[Result]:
        path = newest_with(ctx.root / RESULTS, "ab.json")
        if path is None:
            first = fail_result(names[0], f"no {RESULTS}/<YYYY-MM-DD>/ab.json; run make ab")
            return [first, *not_checked(names[1:], "no ab.json")]
        rel = relpath(path, ctx.root)
        data, why = read_json(path)
        problems = [why] if why else ab_problems(data, fixtures)
        if problems:
            first = fail_result(names[0], f"{rel}: " + "; ".join(problems[:5]))
            return [first, *not_checked(names[1:], f"{rel} breaks the contract")]
        rows = data["fixtures"]
        rules = (min_new_or_tie, Decimal(critic_margin), Decimal(max_mean_cost))
        return [ok_result(names[0], rel), *ab_verdicts(rows, names, rules, Decimal(budget))]

    return Check(READ, names, evaluate)


def ab_problems(data: Any, count: int) -> list[str]:
    """How ab.json breaks the contract: fixtures = exactly `count` objects with name,
    pick in new/old/tie, new and old with critic_total, passed and cost_usd."""
    rows = data.get("fixtures") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return ["fixtures is not a list"]
    problems = []
    if len(rows) != count:
        problems.append(f"fixtures has {len(rows)} entries, need exactly {count}")
    for index, row in enumerate(rows):
        where = f"fixtures[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{where} is not an object")
            continue
        if not isinstance(row.get("name"), str) or not row.get("name"):
            problems.append(f"{where}.name is not a text")
        if row.get("pick") not in ("new", "old", "tie"):
            problems.append(f"{where}.pick is {show(row.get('pick'))}, not new, old or tie")
        for side in ("new", "old"):
            problems += arm_problems(row.get(side), f"{where}.{side}")
    return problems


def arm_problems(arm: Any, where: str) -> list[str]:
    if not isinstance(arm, dict):
        return [f"{where} is not an object"]
    problems = []
    if not is_number(arm.get("critic_total")):
        problems.append(f"{where}.critic_total is {show(arm.get('critic_total'))}")
    if not isinstance(arm.get("passed"), bool):
        problems.append(f"{where}.passed is {show(arm.get('passed'))}")
    cost = arm.get("cost_usd")
    if not is_number(cost) or cost < 0:
        problems.append(f"{where}.cost_usd is {show(cost)}")
    return problems


def ab_verdicts(
    rows: list[dict[str, Any]],
    names: Sequence[str],
    rules: tuple[int, Decimal, Decimal],
    budget: Decimal,
) -> list[Result]:
    """Recompute every A/B rule from the rows; no verdict field in the file is read.
    Means are compared as sums (sum_new >= sum_old - margin * n), so no rounding."""
    min_new_or_tie, margin, max_mean_cost = rules
    n = len(rows)
    picks = [row["pick"] for row in rows]
    new_or_tie = picks.count("new") + picks.count("tie")
    tally = f"new {picks.count('new')}, tie {picks.count('tie')}, old {picks.count('old')}"
    new_total = sum((Decimal(row["new"]["critic_total"]) for row in rows), Decimal(0))
    old_total = sum((Decimal(row["old"]["critic_total"]) for row in rows), Decimal(0))
    means = f"mean new {num(new_total / n)}, mean old {num(old_total / n)}"
    floor = f"floor {num(old_total / n - margin)}"
    lost = [str(r["name"]) for r in rows if r["old"]["passed"] and not r["new"]["passed"]]
    new_cost = sum((Decimal(row["new"]["cost_usd"]) for row in rows), Decimal(0))
    old_cost = sum((Decimal(row["old"]["cost_usd"]) for row in rows), Decimal(0))
    spent = f"new {money(new_cost)} + old {money(old_cost)} = {money(new_cost + old_cost)}"
    return [
        verdict(names[1], new_or_tie >= min_new_or_tie, f"{tally}: {new_or_tie} of {n}"),
        verdict(names[2], new_total >= old_total - margin * n, f"{means}, {floor}"),
        verdict(names[3], not lost, "lost: " + ", ".join(lost) if lost else "none"),
        verdict(names[4], new_cost <= max_mean_cost * n, f"mean new {money(new_cost / n)}"),
        verdict(names[5], new_cost + old_cost <= budget, spent),
    ]


def speech_evals(*prefixes: str, model: str) -> Check:
    """Per prefix: the newest date folder holding <prefix>*-<model>.json; every such
    file there follows the contract and has critic.passed true."""
    names = [f"speech eval: newest {prefix}*-{model}.json passes the critic" for prefix in prefixes]

    def evaluate(ctx: Ctx) -> list[Result]:
        folders = date_folders(ctx.root / RESULTS)
        return [
            speech_verdict(ctx.root, folders, prefix, model, name)
            for prefix, name in zip(prefixes, names)
        ]

    return Check(READ, names, evaluate)


def speech_files(folders: list[Path], prefix: str, model: str) -> list[Path]:
    for folder in folders:
        found = sorted(p for p in folder.glob("*.json") if is_fixture(p.name, prefix, model))
        if found:
            return found
    return []


def is_fixture(filename: str, prefix: str, model: str) -> bool:
    match = RESULT_FILE.match(filename)
    return bool(match and match["model"] == model and match["fixture"].startswith(prefix))


def speech_verdict(root: Path, folders: list[Path], prefix: str, model: str, name: str) -> Result:
    files = speech_files(folders, prefix, model)
    if not files:
        return fail_result(name, f"no {RESULTS}/<YYYY-MM-DD>/{prefix}*-{model}.json")
    problems = []
    for path in files:
        match = RESULT_FILE.match(path.name)
        fixture = match["fixture"] if match else path.name
        data, why = read_json(path)
        found = [why] if why else eval_problems(data, fixture, model)
        if not found and data["critic"]["passed"] is not True:
            found = [f"critic.passed is false (total {data['critic']['total']})"]
        problems += [f"{relpath(path, root)}: {problem}" for problem in found]
    if problems:
        return fail_result(name, "; ".join(problems[:5]))
    return ok_result(name, ", ".join(relpath(path, root) for path in files))


# ------------------------------------------------------------------ step 06: live site


class Fetched:
    """One HTTP answer, or why there was none."""

    def __init__(
        self, status: int | None = None, headers: Any = None, body: bytes = b"", error: str = ""
    ) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.error = error

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def header(self, name: str) -> list[str]:
        if self.headers is None:
            return []
        return [str(value) for value in self.headers.get_all(name) or []]

    def describe(self) -> str:
        return f"HTTP {self.status}" if self.status is not None else self.error


def fetch(url: str, timeout: float = 10) -> Fetched:
    """GET without any proxy (the site is on localhost); redirects are followed."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "reel-studio-gate"})
    try:
        with opener.open(request, timeout=timeout) as answer:
            return Fetched(answer.status, answer.headers, answer.read(MAX_BODY))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(MAX_BODY)
        except (OSError, http.client.HTTPException, AttributeError):
            body = b""
        return Fetched(exc.code, exc.headers, body)
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        return Fetched(error=f"no answer ({getattr(exc, 'reason', None) or exc})")


class Page:
    """A page the live-site check fetches, and what its answer must show."""

    def __init__(
        self,
        path: str,
        html_has: Sequence[str] = (),
        html_lacks: Sequence[str] = (),
        noindex_header: bool = False,
    ) -> None:
        self.path = path
        self.html_has = list(html_has)
        self.html_lacks = list(html_lacks)
        self.noindex_header = noindex_header

    @property
    def name(self) -> str:
        parts = [f"GET {self.path} is 200"]
        if self.html_has:
            parts.append("with " + ", ".join(self.html_has))
        if self.html_lacks:
            parts.append("without " + ", ".join(self.html_lacks))
        if self.noindex_header:
            parts.append("with X-Robots-Tag noindex")
        return " ".join(parts)

    def verdict(self, base: str) -> Result:
        got = fetch(base + self.path)
        if got.status != 200:
            return fail_result(self.name, f"answered {got.describe()}")
        page = got.text().lower()
        problems = []
        lacking = [needle for needle in self.html_has if needle.lower() not in page]
        if lacking:
            problems.append("HTML lacks " + ", ".join(lacking))
        present = [needle for needle in self.html_lacks if needle.lower() in page]
        if present:
            problems.append("HTML contains " + ", ".join(present))
        tags = got.header("X-Robots-Tag")
        if self.noindex_header and not any("noindex" in tag.lower() for tag in tags):
            problems.append("X-Robots-Tag is " + (", ".join(tags) or "missing"))
        return fail_result(self.name, "; ".join(problems)) if problems else ok_result(self.name)


def live_site(
    base: str,
    pages: Sequence[Page],
    *,
    crawlable: Sequence[str],
    config_false: Sequence[str],
    health: str = "/health",
    wait: int = 120,
) -> Check:
    """make up; wait for health; check pages, robots.txt and /api/config; always
    make down at the end, also after a failure."""
    keys = ".".join(config_false)
    up_name = f"make up, then GET {health} is 200 within {wait} s"
    robots_name = "GET /robots.txt is 200 and no Disallow rule matches " + ", ".join(crawlable)
    config_name = f"GET /api/config is JSON with {keys} = false"
    down_name = "make down exits 0"
    names = [up_name, *[page.name for page in pages], robots_name, config_name, down_name]

    def evaluate(ctx: Ctx) -> list[Result]:
        results = []
        try:
            results.append(start_site(ctx, base + health, up_name, wait))
            if results[0].status == FAIL:
                results += not_checked(names[1:-1], "the site did not come up")
            else:
                results += [page.verdict(base) for page in pages]
                results.append(robots_verdict(base, robots_name, crawlable))
                results.append(config_verdict(base, config_name, config_false))
        finally:
            down = ctx.run(("make", "down"))
            if down.ok:
                results.append(ok_result(down_name))
            else:
                results.append(fail_result(down_name, down.why(), down.tail()))
        return results

    return Check(RUN, names, evaluate)


def start_site(ctx: Ctx, url: str, name: str, wait: int) -> Result:
    up = ctx.run(("make", "up"))
    if not up.ok:
        return fail_result(name, f"make up: {up.why()}", up.tail())
    started = time.monotonic()
    while True:
        got = fetch(url, timeout=5)
        waited = time.monotonic() - started
        if got.status == 200:
            return ok_result(name, f"200 after {waited:.0f} s")
        if waited >= wait:
            return fail_result(name, f"no 200 within {wait} s; last: {got.describe()}")
        time.sleep(1)


def robots_verdict(base: str, name: str, crawlable: Sequence[str]) -> Result:
    got = fetch(base + "/robots.txt")
    if got.status != 200:
        return fail_result(name, f"answered {got.describe()}")
    hits = [
        f"'{rule}' blocks {path}"
        for path in crawlable
        for rule in disallow_matches(got.text(), path)
    ]
    return fail_result(name, "; ".join(hits)) if hits else ok_result(name)


def disallow_matches(robots: str, path: str) -> list[str]:
    """Disallow lines whose rule matches `path` with Google's rules: a prefix match,
    `*` for any run of characters, `$` for the end. Allow lines are ignored on purpose:
    a noindex page must not be disallowed at all, or crawlers never see the noindex."""
    hits = []
    for line in robots.splitlines():
        match = DISALLOW.match(line.split("#", 1)[0])
        if match and match.group(1) and robots_rule(match.group(1)).match(path):
            hits.append(line.strip())
    return hits


def robots_rule(rule: str) -> re.Pattern[str]:
    anchored = rule.endswith("$")
    body = rule[:-1] if anchored else rule
    pattern = "".join(".*" if char == "*" else re.escape(char) for char in body)
    return re.compile(pattern + ("$" if anchored else ""))


def config_verdict(base: str, name: str, keys: Sequence[str]) -> Result:
    got = fetch(base + "/api/config")
    if got.status != 200:
        return fail_result(name, f"answered {got.describe()}")
    data, why = parse_json(got.text())
    if why:
        return fail_result(name, f"answered {why}")
    value: Any = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return fail_result(name, f"{'.'.join(keys)} is missing")
        value = value[key]
    return verdict(name, value is False, f"{'.'.join(keys)} is {show(value)}")


# ------------------------------------------------------------------ step 08: smoke


def smoke_from_env() -> Check:
    name = "make smoke URL=<SITE_URL from .env> exits 0"

    def evaluate(ctx: Ctx) -> list[Result]:
        url, why = site_url(ctx.root / ".env")
        if url is None:
            return [fail_result(name, why)]
        ran = ctx.run(("make", "smoke", f"URL={url}"))
        if not ran.ok:
            return [fail_result(name, f"make smoke URL={url}: {ran.why()}", ran.tail())]
        return [ok_result(name, url)]

    return Check(RUN, [name], evaluate)


def site_url(env_file: Path) -> tuple[str | None, str]:
    """SITE_URL from .env. Every other line is read past and never kept or printed."""
    value = None
    try:
        with env_file.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = SITE_URL_LINE.match(line)
                if match:
                    value = env_value(match.group(1))  # the last one wins, as in dotenv
    except FileNotFoundError:
        return None, ".env is missing"
    except OSError as exc:
        return None, f".env cannot be read ({exc.strerror})"
    if not value:
        return None, "SITE_URL is not set in .env"
    if not value.startswith(("https://", "http://")):
        return None, f"SITE_URL in .env is not an http(s) URL: {value}"
    return value, ""


def env_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] in "'\"" and raw[0] in raw[1:]:
        return raw[1 : raw.index(raw[0], 1)]
    return raw.split(" #", 1)[0].strip()


# ------------------------------------------------------------------ self-test

GIT_CONFIG = """\
[user]
\tname = Gate Self-Test
\temail = gate-self-test@example.invalid
[init]
\tdefaultBranch = main
[commit]
\tgpgsign = false
[tag]
\tgpgsign = false
[core]
\tautocrlf = false
"""

FAKE_TOOL = """\
\"\"\"Stand-in for make, uv and gh in the gate self-test; config.json says what to do.\"\"\"
import json
import os
import subprocess
import sys
import time

tool, args = sys.argv[1], sys.argv[2:]
state = os.environ["GATE_FAKE_DIR"]
with open(os.path.join(state, "calls.log"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps([tool, *args]) + "\\n")
with open(os.path.join(state, "config.json"), encoding="utf-8") as handle:
    config = json.load(handle)
if tool == "make" and args[:1] == ["ci"] and config.get("make_ci_sleep"):
    with open(os.path.join(state, "make.pid.part"), "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    os.replace(os.path.join(state, "make.pid.part"), os.path.join(state, "make.pid"))
    time.sleep(config["make_ci_sleep"])
if tool == "make" and args[:1] == ["ci"]:
    git = os.environ["GATE_FAKE_GIT"]
    status = subprocess.run([git, "status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip() and config.get("stamp", True):
        head = subprocess.run([git, "rev-parse", "HEAD"], capture_output=True, text=True)
        with open(".ci-pass", "w", encoding="utf-8") as handle:
            handle.write(config.get("stamp_value", head.stdout.strip()) + "\\n")
    for number in range(20):
        print(f"fake make ci line {number}")
    sys.exit(config.get("make_ci_exit", 0))
if tool == "gh" and args[:2] == ["pr", "view"]:
    print(json.dumps(config["pr"]))
    sys.exit(0)
if tool == "gh" and args[:1] == ["api"]:
    print(json.dumps([{"id": 1, "name": "protect main"}]))
    sys.exit(0)
print("fake " + tool + " " + " ".join(args))
sys.exit(config.get(tool + "_exit", 0))
"""

EBUR128_SAMPLE = """\
[Parsed_ebur128_0 @ 0x1] t: 0.1  TARGET:-23 LUFS  M:-120.7 S:-120.7   I: -70.0 LUFS  LRA: 0.0 LU
[Parsed_ebur128_0 @ 0x1] t: 29.9 TARGET:-23 LUFS  M: -13.9 S: -14.1   I: -14.3 LUFS  LRA: 4.1 LU
[out#0/null @ 0x2] video:0kB audio:258kB subtitle:0kB other streams:0kB
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.4 LUFS

  Loudness range:
    LRA:         4.1 LU
    Threshold: -34.3 LUFS
    LRA low:   -16.9 LUFS
    LRA high:  -12.8 LUFS
"""

GATES = Path(__file__).resolve().parent
Outcome = tuple[bool, str]


def check_run(name: str, status: str, conclusion: str) -> dict[str, str]:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def eval_record(
    fixture: str = "creami",
    model: str = "sonnet",
    cost: Any = 0.98,
    passed: bool = True,
    reads: Sequence[Any] = (0, 5200, 5200),
) -> dict[str, Any]:
    return {
        "fixture": fixture,
        "model": model,
        "cost_usd": cost,
        "critic": {"total": 28, "passed": passed},
        "requests": [{"cache_read_input_tokens": tokens} for tokens in reads],
    }


def ab_record(edit: Callable[[list[dict[str, Any]]], None] | None = None) -> dict[str, Any]:
    """Five fixtures that pass every A/B rule, two of them at the exact limit (mean new
    cost $1.20; picks 3 of 5); `edit` breaks one rule."""
    rows = [
        ("f1", "new", (28, True, 1.10), (27, True, 1.30)),
        ("f2", "tie", (26, True, 1.00), (27, True, 1.20)),
        ("f3", "old", (25, False, 1.25), (26, False, 1.40)),
        ("f4", "new", (29, True, 1.20), (28, True, 1.10)),
        ("f5", "old", (27, True, 1.45), (29, True, 1.50)),
    ]
    fixtures = [
        {
            "name": name,
            "pick": pick,
            "new": {"critic_total": new[0], "passed": new[1], "cost_usd": new[2]},
            "old": {"critic_total": old[0], "passed": old[1], "cost_usd": old[2]},
        }
        for name, pick, new, old in rows
    ]
    if edit is not None:
        edit(fixtures)
    return {"fixtures": fixtures, "verdict": "ignored by the gate"}


def write_files(root: Path, files: dict[str, Any]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            body = content if isinstance(content, str) else json.dumps(content)
            path.write_text(body, encoding="utf-8")


def write_wrapper(path: Path, target: Sequence[str]) -> None:
    """A POSIX sh script that execs `target` with its own arguments."""
    script = "#!/bin/sh\nexec " + " ".join(shlex.quote(part) for part in target) + ' "$@"\n'
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def statuses(results: Sequence[Result]) -> list[str]:
    return [result.status for result in results]


def alive_after(pid: int, seconds: float) -> bool:
    """True when process `pid` still exists after waiting up to `seconds` for it to go."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        if time.monotonic() >= deadline:
            return True
        time.sleep(0.05)


def describe(results: Sequence[Result]) -> str:
    return " | ".join(f"{r.status} {r.name}: {r.detail}" for r in results)


class SelfTest:
    """Throwaway repositories with a bare origin, fake make/uv/gh, and the cases."""

    def __init__(self, tmp: Path, git: str) -> None:
        self.tmp = tmp
        self.state = tmp / "state"
        self.bin = tmp / "bin"
        self.git_only = tmp / "git-only"
        self.empty = tmp / "empty"
        home = tmp / "home"
        for folder in (self.state, self.bin, self.git_only, self.empty, home):
            folder.mkdir()
        (home / ".gitconfig").write_text(GIT_CONFIG, encoding="utf-8")
        tool = tmp / "fake_tool.py"
        tool.write_text(FAKE_TOOL, encoding="utf-8")
        for name in ("make", "uv", "gh"):
            write_wrapper(self.bin / name, [sys.executable, str(tool), name])
        for folder in (self.bin, self.git_only):
            write_wrapper(folder / "git", [git])
        self.real_git = git
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CEILING_DIRECTORIES": str(tmp),
                "PATH": str(self.bin),
                "GATE_FAKE_DIR": str(self.state),
                "GATE_FAKE_GIT": git,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        self.configure()
        self.base = {
            ".gitignore": ".ci-pass\n.lane\n",
            "README.md": "synthetic repository for the gate self-test\n",
            "HANDOFF.md": "# HANDOFF\n",
            "docs/build/STEP-01.md": "# STEP-01\n",
            "docs/build/STEP-04.md": "# STEP-04\n",
            "docs/build/STEP-09.md": "# STEP-09\n",
        }
        self.main = self.repo("main", self.base, {"HANDOFF.md": "# HANDOFF\nWeekly report\n"})

    # ---- plumbing

    def configure(self, **config: Any) -> None:
        (self.state / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (self.state / "calls.log").write_text("", encoding="utf-8")

    def calls(self, tool: str) -> list[list[str]]:
        lines = (self.state / "calls.log").read_text(encoding="utf-8").splitlines()
        argvs = [json.loads(line) for line in lines if line.strip()]
        return [argv[1:] for argv in argvs if argv[0] == tool]

    def git(self, cwd: Path, *args: str) -> str:
        done = subprocess.run(
            [self.real_git, *args],
            cwd=str(cwd),
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
        )
        return text(done.stdout)

    def repo(
        self,
        name: str,
        base: dict[str, Any],
        branch: dict[str, Any] | None = None,
        remote: bool = True,
    ) -> Path:
        """A repository on branch `step`, one commit ahead of main (pushed to a bare
        origin, so origin/main exists) when `branch` is given."""
        work = self.tmp / name
        work.mkdir()
        self.git(work, "init", "-q")
        self.git(work, "symbolic-ref", "HEAD", "refs/heads/main")
        write_files(work, base)
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "-m", "base")
        if remote:
            bare = self.tmp / f"{name}-origin.git"
            self.git(self.tmp, "init", "-q", "--bare", str(bare))
            self.git(work, "remote", "add", "origin", str(bare))
            self.git(work, "push", "-q", "origin", "main")
        if branch is not None:
            self.git(work, "checkout", "-q", "-b", "step")
            write_files(work, branch)
            self.git(work, "add", "-A")
            self.git(work, "commit", "-q", "-m", "step")
        return work

    def gate(
        self, step: str, cwd: Path, *args: str, path: Path | None = None
    ) -> tuple[int, list[str], str]:
        """Run scripts/gates/stepNN.py as a user would; (exit code, lines, output)."""
        env = dict(self.env)
        if path is not None:
            env["PATH"] = str(path)
        done = subprocess.run(
            [sys.executable, str(GATES / f"step{step}.py"), *args],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
        )
        output = text(done.stdout)
        return done.returncode, output.splitlines(), output

    def ctx(self, root: Path) -> Ctx:
        return Ctx(root, True, dict(self.env))

    def scratch(self, name: str, files: dict[str, Any]) -> Path:
        root = self.tmp / name
        root.mkdir()
        write_files(root, files)
        return root

    def head(self, repo: Path) -> str:
        return self.git(repo, "rev-parse", "HEAD").strip()

    # ---- whole gates, run as a user runs them

    def gate_local_pass(self) -> Outcome:
        self.configure()
        code, lines, out = self.gate("09", self.main, "--local")
        skipped = any(line.startswith("skip  pull request") for line in lines)
        good = code == 0 and lines[-1:] == ["GATE step09 PASS"] and skipped
        good = good and not self.calls("gh") and "Traceback" not in out
        return good, f"exit {code}: {flat(out)}"

    def gate_green_pr(self) -> Outcome:
        rollup = [check_run("ci", "COMPLETED", "SUCCESS")]
        pr = {"number": 7, "state": "OPEN", "headRefOid": self.head(self.main)}
        self.configure(pr={**pr, "statusCheckRollup": rollup})
        code, lines, out = self.gate("09", self.main)
        asked = any(argv[:2] == ["pr", "view"] for argv in self.calls("gh"))
        return code == 0 and lines[-1:] == ["GATE step09 PASS"] and asked, flat(out)

    def gate_pending_pr(self) -> Outcome:
        rollup = [check_run("ci", "IN_PROGRESS", "")]
        pr = {"number": 7, "state": "OPEN", "headRefOid": self.head(self.main)}
        self.configure(pr={**pr, "statusCheckRollup": rollup})
        code, lines, out = self.gate("09", self.main)
        flagged = any(line.startswith("FAIL  pull request") for line in lines)
        good = code == 1 and flagged and "CI still running" in out
        return good, flat(out)

    def gate_ci_tail(self) -> Outcome:
        self.configure(make_ci_exit=2)
        code, lines, out = self.gate("09", self.main, "--local")
        at = [i for i, line in enumerate(lines) if line.startswith("FAIL  make ci")]
        want = [f"{INDENT}fake make ci line {number}" for number in range(5, 20)]
        good = code == 1 and bool(at) and lines[at[0] + 1 : at[0] + 16] == want
        good = good and "exit 2" in lines[at[0]] if at else False
        return good, flat(out)

    def gate_dirty_tree(self) -> Outcome:
        self.configure()
        self.gate("09", self.main, "--local")  # leaves .ci-pass = HEAD from a clean run
        (self.main / "README.md").write_text("changed\n", encoding="utf-8")
        try:
            code, lines, out = self.gate("09", self.main, "--local")
        finally:
            self.git(self.main, "checkout", "-q", "--", "README.md")
        fail = [line for line in lines if line.startswith("FAIL  make ci")]
        good = code == 1 and bool(fail) and "dirty" in fail[0] and "clean tree" in fail[0]
        return good, flat(out)

    def gate_no_stamp(self) -> Outcome:
        (self.main / ".ci-pass").unlink(missing_ok=True)
        self.configure(stamp=False)
        code, _lines, out = self.gate("09", self.main, "--local")
        return code == 1 and ".ci-pass is missing" in out, flat(out)

    def gate_wrong_stamp(self) -> Outcome:
        self.configure(stamp_value="0" * 40)
        code, _lines, out = self.gate("09", self.main, "--local")
        return code == 1 and ".ci-pass holds 000000000000" in out, flat(out)

    def gate_missing_commands(self) -> Outcome:
        self.configure()
        code, lines, out = self.gate("09", self.main, "--local", path=self.git_only)
        good = code == 1 and "make: command not found" in out and "uv: command not found" in out
        good = good and "Traceback" not in out and lines[-1].startswith("GATE step09 FAIL (")
        return good, flat(out)

    def gate_no_git(self) -> Outcome:
        code, lines, out = self.gate("09", self.main, "--local", path=self.empty)
        want = [
            "FAIL  repository root: git: command not found",
            "GATE step09 FAIL (1 of 1 checks failed)",
        ]
        return code == 2 and lines == want, flat(out)

    def gate_not_a_repo(self) -> Outcome:
        plain = self.scratch("plain", {"README.md": "no git here\n"})
        code, lines, out = self.gate("01", plain, "--local")
        good = code == 2 and "not inside a git repository" in out and "Traceback" not in out
        return good and lines[-1] == "GATE step01 FAIL (1 of 1 checks failed)", flat(out)

    def gate_foreign_repo(self) -> Outcome:
        foreign = self.repo("foreign", {"README.md": "another project\n"}, remote=False)
        code, _lines, out = self.gate("01", foreign, "--local")
        return code == 2 and "docs/build/STEP-01.md is missing" in out, flat(out)

    def gate_bad_argument(self) -> Outcome:
        code, _lines, out = self.gate("09", self.main, "--bogus")
        return code == 2 and "usage: python3 scripts/gates/step09.py" in out, flat(out)

    def gate_missing_files(self) -> Outcome:
        self.configure()
        code, lines, out = self.gate("01", self.main, "--local", path=self.bin)
        files = [line for line in lines if line.startswith("FAIL  25 required files")]
        good = code == 1 and bool(files) and "LICENSE" in files[0] and "Traceback" not in out
        skips = sum(1 for line in lines if line.startswith("skip  "))
        return good and skips == 2 and not self.calls("gh"), flat(out)

    def gate_bad_json(self) -> Outcome:
        branch = {
            "HANDOFF.md": "# HANDOFF\nA/B\n",
            "eval/AB-RESULT.md": "# A/B\n",
            "eval/results/2026-10-09/ab.json": "{bad",
        }
        repo = self.repo("ab-bad", self.base, branch)
        self.configure()
        code, lines, out = self.gate("04", repo, "--local")
        bad = [line for line in lines if line.startswith("FAIL  A/B evidence")]
        good = code == 1 and bool(bad) and "not valid JSON" in bad[0]
        later = sum(1 for line in lines if "not checked: eval/results" in line)
        return good and later == 5 and "Traceback" not in out, flat(out)

    def gate_sigterm(self) -> Outcome:
        self.configure(make_ci_sleep=60)
        pid_file = self.state / "make.pid"
        gate = subprocess.Popen(
            [sys.executable, str(GATES / "step09.py"), "--local"],
            cwd=str(self.main),
            env=dict(self.env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        while not pid_file.exists() and gate.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        gate.send_signal(signal.SIGTERM)
        output = text(gate.communicate(timeout=60)[0])
        make_pid = int(pid_file.read_text(encoding="utf-8")) if pid_file.exists() else 0
        pid_file.unlink(missing_ok=True)
        orphan = make_pid > 0 and alive_after(make_pid, seconds=2)
        if orphan:
            with contextlib.suppress(OSError):
                os.kill(make_pid, signal.SIGKILL)
        stopped = "FAIL  make ci exits 0 and .ci-pass equals HEAD: interrupted" in output
        good = gate.returncode == 2 and stopped and make_pid > 0 and not orphan
        return good, f"exit {gate.returncode}, make pid {make_pid}, orphan {orphan}: {flat(output)}"

    def gate_bug_is_a_line(self) -> Outcome:
        def broken(_ctx: Ctx) -> list[Result]:
            raise ZeroDivisionError("planted")

        self.configure()
        buffer = io.StringIO()
        boom = Check(READ, ["planted bug"], broken)
        env = dict(self.env)
        code = run_gate("09", [boom], ["--local"], buffer, str(self.main), env)
        out = buffer.getvalue()
        good = code == 2 and "FAIL  planted bug: gate error ZeroDivisionError" in out
        return good and "Traceback" not in out, flat(out)

    # ---- helpers, called directly

    def files_missing(self) -> Outcome:
        results = exists("README.md", "nope/a.txt", "nope/b.txt").evaluate(self.ctx(self.main))
        detail = results[0].detail
        good = statuses(results) == [FAIL] and "nope/a.txt, nope/b.txt" in detail
        return good and "README.md" not in detail, describe(results)

    def file_checks(self) -> Outcome:
        sha = "a" * 40
        root = self.scratch(
            "files",
            {
                "web.md": "# Web\n- iPhone upload: 300 MB .mov, done\n",
                "cloud.md": "Phone order pending\n",
                ".gitignore": ".env\n.lane\n",
                "ci.yml": f"steps:\n  - uses: actions/checkout@{sha} # v4\n  - uses: x/y@v4\n",
                ".github/workflows/ci.yml": "on: push\n",
                ".github/workflows/.DS_Store": "",
            },
        )
        ctx = self.ctx(root)
        got = [
            line_starting("web.md", "iPhone upload:").evaluate(ctx)[0].status,
            line_starting("cloud.md", "Phone order:").evaluate(ctx)[0].status,
            has_lines(".gitignore", ".env", ".lane").evaluate(ctx)[0].status,
            has_lines(".gitignore", ".env", "data/").evaluate(ctx)[0].status,
            contains("missing.txt", "x").evaluate(ctx)[0].status,
            workflows("ci.yml").evaluate(ctx)[0].status,
            workflows("ci.yml", "deploy.yml").evaluate(ctx)[0].status,
        ]
        pinned = actions_pinned("ci.yml").evaluate(ctx)[0]
        want = [OK, FAIL, OK, FAIL, FAIL, OK, FAIL]
        good = got == want and pinned.status == FAIL and pinned.detail == "not pinned: x/y@v4"
        return good, f"{got} {pinned.detail}"

    def eval_cases(self) -> Outcome:
        check = eval_evidence("creami", model="sonnet", max_cost="1.20", cheaper="haiku")
        haiku = {"2026-10-01/creami-haiku.json": eval_record(model="haiku", cost=0.05)}
        old = {"2026-10-08/creami-sonnet.json": eval_record(cost=2.00, passed=False)}
        scenarios = [
            ("pass at the cap", {"2026-10-09/creami-sonnet.json": eval_record(cost=1.20)}, "OOOOO"),
            ("newest over cap", {"2026-10-09/creami-sonnet.json": eval_record(cost=1.21)}, "OFOOO"),
            (
                "critic failed",
                {"2026-10-09/creami-sonnet.json": eval_record(passed=False)},
                "OOFOO",
            ),
            ("one request", {"2026-10-09/creami-sonnet.json": eval_record(reads=(0,))}, "OOOFO"),
            (
                "cache miss",
                {"2026-10-09/creami-sonnet.json": eval_record(reads=(0, 9, 0))},
                "OOOFO",
            ),
            ("bad JSON", {"2026-10-09/creami-sonnet.json": "{bad"}, "FFFFO"),
            ("bool cost", {"2026-10-09/creami-sonnet.json": eval_record(cost=True)}, "FFFFO"),
            (
                "float tokens",
                {"2026-10-09/creami-sonnet.json": eval_record(reads=(0, 1.5))},
                "FFFFO",
            ),
            ("wrong fixture", {"2026-10-09/creami-sonnet.json": eval_record("other")}, "FFFFO"),
        ]
        problems = []
        for index, (label, newest, want) in enumerate(scenarios):
            files = {f"{RESULTS}/{k}": v for k, v in {**old, **haiku, **newest}.items()}
            results = check.evaluate(self.ctx(self.scratch(f"eval{index}", files)))
            got = "".join("O" if r.status == OK else "F" for r in results)
            if got != want:
                problems.append(f"{label}: got {got}, want {want}: {describe(results)}")
        no_haiku = self.scratch(
            "eval-nohaiku", {f"{RESULTS}/2026-10-09/creami-sonnet.json": eval_record()}
        )
        last = check.evaluate(self.ctx(no_haiku))[-1]
        if last.status != FAIL:
            problems.append("missing creami-haiku.json passed")
        bad = self.scratch("eval-badjson", {f"{RESULTS}/2026-10-09/creami-sonnet.json": "{bad"})
        first = check.evaluate(self.ctx(bad))[0]
        if "not valid JSON" not in first.detail:
            problems.append(f"bad JSON reason: {first.detail}")
        return not problems, "; ".join(problems)

    def budget_cases(self) -> Outcome:
        check = results_budget("5.00")
        dated = f"{RESULTS}/2026-10-09"
        base = {
            **self.base,
            f"{RESULTS}/2026-10-01/old-sonnet.json": eval_record("old", cost=9.99),
            f"{RESULTS}/2026-10-01/edit-sonnet.json": eval_record("edit", cost=0.50),
        }
        within_cap = {
            f"{dated}/creami-haiku.json": eval_record(model="haiku", cost=0.05),
            f"{dated}/creami-sonnet.json": eval_record(cost=1.10),
            f"{RESULTS}/2026-10-01/edit-sonnet.json": eval_record("edit", cost=4.50),
        }
        over = {
            f"{dated}/f{i}-sonnet.json": eval_record(f"f{i}", cost=c)
            for i, c in enumerate((2, 2, 1.01))
        }
        broken = {f"{dated}/notes.json": {"note": "no cost here"}}
        runs = [
            ("within cap", self.repo("budget-ok", base, within_cap), OK, "$1.15 in 2 files"),
            ("over cap", self.repo("budget-over", self.base, over), FAIL, "$5.01 in 3 files"),
            ("no cost_usd", self.repo("budget-bad", self.base, broken), FAIL, "notes.json"),
            (
                "no origin",
                self.repo("budget-solo", self.base, over, remote=False),
                FAIL,
                "fetch origin first",
            ),
        ]
        problems = []
        for label, repo, want, words in runs:
            result = check.evaluate(self.ctx(repo))[0]
            if result.status != want or words not in result.detail:
                problems.append(f"{label}: {result.status} {result.detail}")
        return not problems, "; ".join(problems)

    def ab_cases(self) -> Outcome:
        check = ab_gate(
            fixtures=5, min_new_or_tie=3, critic_margin=1, max_mean_cost="1.20", budget="15.00"
        )

        def set_value(
            row: int, side: str, key: str, value: Any
        ) -> Callable[[list[dict[str, Any]]], None]:
            def edit(rows: list[dict[str, Any]]) -> None:
                if side:
                    rows[row][side][key] = value
                else:
                    rows[row][key] = value

            return edit

        def chain(
            *edits: Callable[[list[dict[str, Any]]], None],
        ) -> Callable[[list[dict[str, Any]]], None]:
            def edit(rows: list[dict[str, Any]]) -> None:
                for one in edits:
                    one(rows)

            return edit

        scenarios: list[tuple[str, Any, str]] = [
            ("all rules pass, cost at the limit", ab_record(), "OOOOOO"),
            (
                "critic exactly at the floor",
                ab_record(set_value(0, "new", "critic_total", 25)),
                "OOOOOO",
            ),
            ("picks 2 of 5", ab_record(set_value(0, "", "pick", "old")), "OFOOOO"),
            (
                "mean critic below the floor",
                ab_record(
                    chain(
                        set_value(0, "new", "critic_total", 24),
                        set_value(3, "new", "critic_total", 25),
                    )
                ),
                "OOFOOO",
            ),
            ("fixture lost", ab_record(set_value(1, "new", "passed", False)), "OOOFOO"),
            ("mean cost 1.21", ab_record(set_value(4, "new", "cost_usd", 1.50)), "OOOOFO"),
            ("budget 21.00", ab_record(set_value(4, "old", "cost_usd", 10.00)), "OOOOOF"),
            ("4 fixtures", {"fixtures": ab_record()["fixtures"][:4]}, "FFFFFF"),
            ("pick maybe", ab_record(set_value(2, "", "pick", "maybe")), "FFFFFF"),
            ("negative cost", ab_record(set_value(2, "old", "cost_usd", -1)), "FFFFFF"),
            ("bad JSON", "{bad", "FFFFFF"),
        ]
        problems = []
        for index, (label, record, want) in enumerate(scenarios):
            root = self.scratch(f"ab{index}", {f"{RESULTS}/2026-10-09/ab.json": record})
            results = check.evaluate(self.ctx(root))
            got = "".join("O" if r.status == OK else "F" for r in results)
            if got != want:
                problems.append(f"{label}: got {got}, want {want}: {describe(results)}")
        files = {
            f"{RESULTS}/2026-10-08/ab.json": ab_record(),
            f"{RESULTS}/2026-10-09/ab.json": ab_record(set_value(0, "", "pick", "old")),
        }
        newest = check.evaluate(self.ctx(self.scratch("ab-newest", files)))
        if statuses(newest)[1] != FAIL:
            problems.append("an older passing ab.json hid the newest one")
        numbers = check.evaluate(
            self.ctx(self.scratch("ab-numbers", {f"{RESULTS}/2026-10-09/ab.json": ab_record()}))
        )
        shown_numbers = " ".join(result.detail for result in numbers)
        for words in (
            "new 2, tie 1, old 2: 3 of 5",
            "mean new 27.00, mean old 27.40",
            "$1.20",
            "$12.50",
        ):
            if words not in shown_numbers:
                problems.append(f"computed numbers lack '{words}': {shown_numbers}")
        missing = check.evaluate(self.ctx(self.scratch("ab-missing", {"README.md": "x"})))
        if statuses(missing) != [FAIL] * 6:
            problems.append("a missing ab.json did not fail every line")
        return not problems, "; ".join(problems)

    def speech_cases(self) -> Outcome:
        check = speech_evals("long_take", "talking", "tutorial", model="sonnet")
        day, before = f"{RESULTS}/2026-10-20", f"{RESULTS}/2026-10-19"
        good_files = {
            f"{before}/long_take-sonnet.json": eval_record("long_take"),
            f"{day}/talking_es1-sonnet.json": eval_record("talking_es1"),
            f"{day}/talking_es2-sonnet.json": eval_record("talking_es2"),
            f"{day}/tutorial-sonnet.json": eval_record("tutorial"),
        }
        bad_files = {
            **good_files,
            f"{before}/talking_es2-sonnet.json": eval_record("talking_es2"),
            f"{day}/talking_es2-sonnet.json": eval_record("talking_es2", passed=False),
            f"{day}/tutorial-sonnet.json": None,
            f"{day}/tutorial-haiku.json": eval_record("tutorial", model="haiku"),
        }
        bad_files = {k: v for k, v in bad_files.items() if v is not None}
        good = check.evaluate(self.ctx(self.scratch("speech-good", good_files)))
        bad = check.evaluate(self.ctx(self.scratch("speech-bad", bad_files)))
        ok_all = statuses(good) == [OK, OK, OK]
        ok_bad = statuses(bad) == [OK, FAIL, FAIL] and "talking_es2" in bad[1].detail
        return ok_all and ok_bad, f"{describe(good)} || {describe(bad)}"

    def media_cases(self) -> Outcome:
        spec = Spec(1080, 1920, "30/1", "h264", "aac", -14, 1.0)
        video = {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1080,
            "height": 1920,
            "avg_frame_rate": "30/1",
        }
        audio = {"codec_type": "audio", "codec_name": "aac"}
        probe = {"streams": [video, audio], "format": {"duration": "29.966667"}}
        slow = {
            "streams": [{**video, "avg_frame_rate": "30000/1001"}, audio],
            "format": {"duration": "1"},
        }
        mute = {"streams": [video], "format": {"duration": "0.000000"}}
        problems = []
        if probe_problems(parse_json(json.dumps(probe))[0], spec):
            problems.append("a good probe failed")
        if "30000/1001" not in " ".join(probe_problems(slow, spec)):
            problems.append("a 29.97 fps probe passed")
        if len(probe_problems(mute, spec)) != 2:
            problems.append("missing audio and zero duration not both reported")
        loudness = integrated_loudness(EBUR128_SAMPLE)
        if loudness != Decimal("-14.2"):
            problems.append(f"loudness parser read {loudness}, want -14.2 (the summary)")
        if integrated_loudness("no summary here") is not None:
            problems.append("loudness parser invented a value")
        edges = [
            within(Decimal(v), Decimal(-14), Decimal("1.0"))
            for v in ("-15.0", "-12.9", "-inf", "nan")
        ]
        if edges != [True, False, False, False]:
            problems.append(f"loudness tolerance edges: {edges}")
        qa_cases = [
            ({"hard_checks": {"text": {"size": True}, "clean": {"size": True}}}, OK),
            ({"hard_checks": {"text": {"size": True}, "clean": {"size": False}}}, FAIL),
            ({"hard_checks": {}}, FAIL),
            ({"hard_checks": {"lufs": -14}}, FAIL),
            ("{bad", FAIL),
        ]
        for index, (body, want) in enumerate(qa_cases):
            root = self.scratch(f"qa{index}", {"qa.json": body})
            result = qa_verdict("qa", root / "qa.json")
            if result.status != want:
                problems.append(f"qa case {index}: {result.status} {result.detail}")
        return not problems, "; ".join(problems)

    def tree_cases(self) -> Outcome:
        root = self.scratch("tree", {"a.mov": b"\x00\x01", "b/c.jpg": b"c", "d.txt": "d"})
        before = hash_tree(root)
        same = tree_verdict("tree", before, hash_tree(root))
        (root / "a.mov").write_bytes(b"\x00\x02")
        (root / "b" / "new.mov").write_bytes(b"n")
        (root / "d.txt").unlink()
        moved = tree_verdict("tree", before, hash_tree(root))
        want = "changed: a.mov; added: b/new.mov; removed: d.txt"
        return (same.status == OK and moved.detail == want, f"{same.detail} | {moved.detail}")

    def robots_cases(self) -> Outcome:
        robots = "User-agent: *\nDisallow: /old\nDisallow:\nDisallow: /*.json$\n"
        blocking = [
            ("Disallow: /o/", "/o/gate-check"),
            ("disallow:/o", "/o/gate-check"),
            ("Disallow: /", "/new"),
            ("Disallow: /*check", "/o/gate-check"),
            ("Disallow: /n", "/new"),
        ]
        problems = [
            f"{p} blocked" for p in ("/o/gate-check", "/new") if disallow_matches(robots, p)
        ]
        problems += [
            f"{rule} let {path} through"
            for rule, path in blocking
            if not disallow_matches(rule, path)
        ]
        return not problems, "; ".join(problems)

    def pr_cases(self) -> Outcome:
        head = "c" * 40

        def pr(state: str, rollup: Any, sha: str = head) -> dict[str, Any]:
            return {"number": 1, "state": state, "headRefOid": sha, "statusCheckRollup": rollup}

        context = {"__typename": "StatusContext", "context": "lint", "state": "SUCCESS"}
        green = [check_run("ci", "COMPLETED", "SUCCESS"), context]
        waiting = [{**context, "state": "PENDING"}]
        cases = [
            (pr("OPEN", green), True, "2 checks SUCCESS"),
            (pr("MERGED", None), False, "no status checks"),
            (pr("OPEN", [check_run("ci", "COMPLETED", "FAILURE")]), False, "failed: ci FAILURE"),
            (pr("OPEN", waiting), False, "CI still running: lint"),
            (pr("CLOSED", green), False, "OPEN or MERGED"),
            (pr("OPEN", green, sha="d" * 40), False, "push or pull"),
        ]
        problems = []
        for data, want, words in cases:
            good, detail = pr_verdict(data, head)
            if good != want or words not in detail:
                problems.append(f"{data['state']}: {good} {detail}")
        return not problems, "; ".join(problems)

    def secret_cases(self) -> Outcome:
        shaped = "sk-" + "ant-" + "api03-" + "Q" * 40
        url = "https://reel-api-123456.europe-west1.run.app"
        root = self.scratch(
            "dotenv",
            {".env": "ANTHROPIC_API_KEY=" + shaped + "\n# note\nSITE_URL='" + url + "'  # beta\n"},
        )
        self.configure()
        results = smoke_from_env().evaluate(self.ctx(root))
        buffer = io.StringIO()
        report = Report("08", buffer, {"DEMO_API_TOKEN": "tok" + "9" * 20})
        for result in results:
            report.add(result)
        report.add(fail_result("demo", "saw " + shaped, ["value tok" + "9" * 20 + " here"]))
        out = buffer.getvalue()
        made = self.calls("make") == [["smoke", f"URL={url}"]]
        clean = shaped not in out and "9" * 20 not in out and out.count("[redacted]") == 2
        return results[0].status == OK and url in out and made and clean, flat(out)

    def text_cases(self) -> Outcome:
        problems = []
        counts = [
            passed_count("\x1b[32m31 passed\x1b[0m, 2 deselected in 3.21s"),
            passed_count("1 failed, 2 passed in 0.5s"),
            passed_count("no tests ran"),
        ]
        if counts != [31, 2, 0]:
            problems.append(f"pytest counts {counts}")
        lines = last_lines("a\nprogress 10%\rprogress 90%\rdone\n\x1b[31mred\x1b[0m\n\n\n")
        if lines != ["a", "done", "red"]:
            problems.append(f"tail cleaning {lines}")
        if len(last_lines("\n".join(str(n) for n in range(40)))) != TAIL:
            problems.append("tail is not 15 lines")
        return not problems, "; ".join(problems)

    def sdk_cases(self) -> Outcome:
        planted = self.scratch(
            "sdk",
            {
                "reel_studio/editor/loop.py": "import os\nfrom claude_agent_sdk import query\n",
                "reel_studio/__pycache__/loop.cpython-313.pyc": b"tool_runner",
                "pyproject.toml": "[project]\nname = 'reel-studio'\n",
            },
        )
        clean = self.scratch("sdk-clean", {"reel_studio/core/ports.py": "class Claude: ...\n"})
        bad = no_agent_sdk().evaluate(self.ctx(planted))[0]
        good = no_agent_sdk().evaluate(self.ctx(clean))[0]
        found = bad.status == FAIL and "reel_studio/editor/loop.py:2 claude_agent_sdk" in bad.detail
        return (
            found and ".pyc" not in bad.detail and good.status == OK,
            f"{bad.detail} | {good.detail}",
        )

    def lane_case(self) -> Outcome:
        (self.main / ".lane").write_text("web\n", encoding="utf-8")
        try:
            result = handoff_changed().evaluate(self.ctx(self.main))[0]
        finally:
            (self.main / ".lane").unlink()
        main = handoff_changed().evaluate(self.ctx(self.main))[0]
        good = result.status == FAIL and "docs/handoff/web.md is not among" in result.detail
        return (good and main.status == OK, f"{result.name}: {result.detail} | {main.detail}")

    def cases(self) -> list[tuple[str, Callable[[], Outcome]]]:
        return [
            ("step09 --local passes in a clean repo and never calls gh", self.gate_local_pass),
            ("step09 without --local asks gh and passes on green checks", self.gate_green_pr),
            ("pending CI fails with 'CI still running'", self.gate_pending_pr),
            ("a red make ci prints its last 15 lines, indented", self.gate_ci_tail),
            ("a dirty tree fails make ci even with a stamp from a clean run", self.gate_dirty_tree),
            ("make ci without a stamp fails", self.gate_no_stamp),
            ("a stamp that is not HEAD fails", self.gate_wrong_stamp),
            ("missing make and uv are FAIL lines, not tracebacks", self.gate_missing_commands),
            ("no git on PATH: one FAIL line, exit 2", self.gate_no_git),
            ("outside a git repository: FAIL line, exit 2", self.gate_not_a_repo),
            ("a repository without the step's build doc is refused", self.gate_foreign_repo),
            ("an unknown argument: usage FAIL line, exit 2", self.gate_bad_argument),
            (
                "step01 --local lists missing files and skips 2 GitHub checks",
                self.gate_missing_files,
            ),
            ("step04 with a broken ab.json: FAIL line, no traceback", self.gate_bad_json),
            ("SIGTERM stops the gate and kills the running make ci", self.gate_sigterm),
            ("a bug inside a check is a FAIL line and exit 2", self.gate_bug_is_a_line),
            ("missing files are named in one FAIL line", self.files_missing),
            ("line, lines, contains, workflows and pinned-SHA checks", self.file_checks),
            ("eval evidence: cap, critic, cache, contract, newest folder", self.eval_cases),
            ("budget sums only files added on the branch", self.budget_cases),
            ("A/B: one sample passes, each rule has a failing sample", self.ab_cases),
            ("speech evals: newest per prefix, every match must pass", self.speech_cases),
            ("ffprobe spec, loudness parser (last I:), qa hard_checks", self.media_cases),
            ("input hashes catch changed, added and removed files", self.tree_cases),
            ("robots.txt rules that block a noindex page", self.robots_cases),
            ("pull request verdicts", self.pr_cases),
            ("SITE_URL is the only .env value read; keys are redacted", self.secret_cases),
            ("pytest counts and output tails", self.text_cases),
            ("Agent SDK mentions found with file:line, .pyc ignored", self.sdk_cases),
            ("a lane's handoff file is docs/handoff/<lane>.md", self.lane_case),
        ]


def self_test() -> int:
    outcomes: list[tuple[str, bool, str]] = []
    git = shutil.which("git")
    if git is None:
        outcomes.append(("git is on PATH", False, "install git"))
    else:
        with TempDir("gate-self-test-") as tmp:
            try:
                suite = SelfTest(tmp, git)
            except Exception as exc:  # noqa: BLE001 - setup failed: report it as a case
                outcomes.append(("build throwaway repositories", False, gate_bug(exc)))
            else:
                for name, case in suite.cases():
                    try:
                        good, detail = case()
                    except Exception as exc:  # noqa: BLE001 - a crash is a failed case
                        good, detail = False, gate_bug(exc)
                    outcomes.append((name, good, detail))
    for name, good, detail in outcomes:
        print(f"PASS {name}" if good else f"FAIL {name}: {detail[:1500]}")
    failed = sum(1 for _name, good, _detail in outcomes if not good)
    print(f"self-test: {len(outcomes) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    quiet_bad_bytes()
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    sys.stderr.write("usage: python3 scripts/gates/_gate.py --self-test\n")
    sys.stderr.write("(the gates themselves are scripts/gates/stepNN.py [--local])\n")
    sys.exit(2)
