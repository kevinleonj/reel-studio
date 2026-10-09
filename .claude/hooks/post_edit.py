#!/usr/bin/env python3
"""PostToolUse hook for Edit, Write and MultiEdit (F54). Python 3.9+ standard library only.

1. Formats and lints an edited Python file with ruff when the project is set up. Remaining
   lint errors go back to Claude as feedback ({"decision": "block", "reason": ...}).
2. Runs scripts/check_literals.py on reel_studio/**/*.py and web/src/**/*.{ts,tsx,astro,css} once
   that script exists. The scanner needs Python 3.11+ (tomllib), so it runs through
   `uv run --python 3.13` when uv is on PATH, otherwise through python3. Violations exit 2, which
   shows stderr to Claude. A scanner that fails or hangs never blocks; Claude gets the warning as
   PostToolUse additionalContext instead.
The edit itself has already happened. Silent when ruff, the project or the scanner is not there yet.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True                      # importing _common must leave no __pycache__ here
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

LITERAL_HOMES = ("Move the value to its home (config/*.toml, reel_studio/settings.py, "
                 "reel_studio/core/constants.py, web/src/copy/en.json or web/src/styles/tokens.css) "
                 "or add an allowlist entry with a reason (needs Kevin).")
WEB_SUFFIXES = (".ts", ".tsx", ".astro", ".css")
SCANNER_PYTHON = "3.13"
LITERAL_TIMEOUT_S = 30
MAX_VIOLATION_LINES = 40


def ruff_problems(root: Path, path: Path, raw: str) -> str | None:
    """Format and lint one Python file with ruff; the leftover problems, or None."""
    if not raw.endswith(".py") or not (root / "pyproject.toml").exists() or not shutil.which("uv"):
        return None
    base = ["uv", "run", "--frozen", "--quiet", "ruff"]
    try:
        subprocess.run([*base, "format", str(path)], cwd=root, capture_output=True, timeout=60)
        result = subprocess.run([*base, "check", "--fix", str(path)], cwd=root,
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return None
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-30:])
    return f"ruff still reports problems in {path.name}:\n{tail}"


def in_literal_scope(rel: str) -> bool:
    low = rel.lower()                                # the default macOS file system ignores case
    return (low.startswith("reel_studio/") and low.endswith(".py")) or \
        (low.startswith("web/src/") and low.endswith(WEB_SUFFIXES))


def scanner_command(script: Path, path: Path) -> list[str]:
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--quiet", "--no-project", "--python", SCANNER_PYTHON, "python", str(script), str(path)]
    return [shutil.which("python3") or sys.executable, str(script), str(path)]


def literal_violations(root: Path, path: Path, rel: str) -> tuple[str | None, str | None]:
    """(violations, warning) from scripts/check_literals.py: exit 1 = violations on stdout,
    0 = clean, 2 = its own error. A crash, a missing Python or a timeout is a warning, never a block."""
    script = root / "scripts" / "check_literals.py"
    if not in_literal_scope(rel) or not script.is_file():
        return None, None
    skipped = f"The literal check of {rel} was skipped; run scripts/check_literals.py yourself or tell Kevin."
    try:
        run = subprocess.run(scanner_command(script, path), cwd=root, capture_output=True, text=True,
                             timeout=LITERAL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, f"scripts/check_literals.py took over {LITERAL_TIMEOUT_S} s. {skipped}"
    except OSError as exc:
        return None, f"scripts/check_literals.py could not start ({exc.__class__.__name__}). {skipped}"
    lines = run.stdout.strip().splitlines()
    if run.returncode == 0:
        return None, None
    if run.returncode != 1 or not lines:             # 2 = the scanner's own error; 1 with no output = a crash
        errors = run.stderr.strip().splitlines()
        detail = f": {errors[-1][:200]}" if errors else ""
        return None, f"scripts/check_literals.py failed (exit {run.returncode}{detail}). {skipped}"
    if len(lines) > MAX_VIOLATION_LINES:
        lines = [*lines[:MAX_VIOLATION_LINES], f"... and {len(lines) - MAX_VIOLATION_LINES} more"]
    return "\n".join(lines), None


def main() -> None:
    data = _common.read_input(sys.stdin)
    if data is None:
        sys.exit(0)
    raw = str(_common.tool_input(data).get("file_path") or "")
    if not raw:
        sys.exit(0)
    root = _common.repo_root(data)
    path = Path(raw)
    if not path.is_absolute():
        path = Path(data.get("cwd") or root) / path
    path = path.resolve()
    if root not in path.parents or not path.exists():
        sys.exit(0)
    rel = path.relative_to(root).as_posix()

    lint = ruff_problems(root, path, raw)
    violations, warning = literal_violations(root, path, rel)
    if violations:
        # Exit 2 shows stderr to Claude. A JSON reason on stdout would replace it, so ruff's
        # leftovers travel in the same stderr text.
        report = [lint] if lint else []
        report += [f"scripts/check_literals.py found hard-coded values in {rel}:", violations, LITERAL_HOMES]
        sys.stderr.write("\n".join(report) + "\n")
        sys.exit(2)
    output: dict = {}
    if lint:
        output.update(decision="block", reason=lint)
    if warning:                                      # stderr on exit 0 would reach the debug log only
        output["hookSpecificOutput"] = {"hookEventName": "PostToolUse", "additionalContext": warning}
    if output:
        print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
