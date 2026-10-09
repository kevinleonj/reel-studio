#!/usr/bin/env python3
"""Helpers shared by the guard hooks. Python 3.9+ standard library only; git is the only program run.

Claude Code runs each hook as `python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/<hook>.py"`. On a Mac that
python3 can be the Xcode Command Line Tools' 3.9, so nothing here may need a newer Python (no tomllib,
no `match`, no runtime `X | Y`). Every hook puts this folder on sys.path itself and turns bytecode
writing off before importing this module, so no __pycache__ appears in .claude/hooks/.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Iterable

MAIN = "main"
LANE_FILE = ".lane"                      # untracked, one word, written by scripts/dev/lane.sh
LANES_FILE = ".claude/lanes.json"
TEMP_FOLDERS = ("/tmp", "/private/tmp")  # macOS links /tmp to /private/tmp


def read_input(stream: IO[str]) -> dict[str, Any] | None:
    """The hook's JSON object from stdin, or None when stdin is not a JSON object."""
    try:
        data = json.load(stream)
    except ValueError:                   # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        return None
    return data if isinstance(data, dict) else None


def tool_input(data: dict[str, Any]) -> dict[str, Any]:
    value = data.get("tool_input")
    return value if isinstance(value, dict) else {}


def git(cwd: Path | str, *args: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    """`git -C <cwd> <args>` with text output captured. Raises OSError or SubprocessError."""
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)


def repo_root(data: dict[str, Any]) -> Path:
    """Root of the git worktree the session works in; each worktree is its own root.

    Claude Code keeps CLAUDE_PROJECT_DIR where the session started but reports the current
    directory as `cwd`, so the root is `git rev-parse --show-toplevel` run in `cwd`.
    Falls back to CLAUDE_PROJECT_DIR, then to the cwd itself.
    """
    cwd = str(data.get("cwd") or "") or _process_cwd()
    try:
        top = git(cwd, "rev-parse", "--show-toplevel", timeout=10)
        if top.returncode == 0 and top.stdout.strip():
            return Path(top.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()


def _process_cwd() -> str:
    try:
        return os.getcwd()
    except OSError:
        return "."


def real_dirs(candidates: Iterable[str]) -> list[Path]:
    """Real paths of the candidates that are existing folders, without duplicates and never /."""
    found: list[Path] = []
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            real = Path(os.path.realpath(candidate))
            if real != Path(real.anchor) and real not in found:
                found.append(real)
    return found


def temp_roots() -> list[Path]:
    """Where temp writes and rm are fine: /tmp, /private/tmp, Python's temp folder and $TMPDIR.

    On macOS /tmp is a link to /private/tmp and $TMPDIR lives under /var/folders, which is really
    /private/var/folders, so roots and paths are both compared as real paths.
    """
    return real_dirs([*TEMP_FOLDERS, tempfile.gettempdir(), os.environ.get("TMPDIR", "")])


def inside(path: Path | str, roots: Iterable[Path]) -> bool:
    """True when the real path of `path` lies strictly inside one of `roots` (already real)."""
    real = Path(os.path.realpath(path))
    return any(root in real.parents for root in roots)


def starts_with(rel: str, prefixes: Iterable[str]) -> bool:
    """Prefix match that ignores case: the default macOS file system treats Docs/ and docs/ as one."""
    return rel.lower().startswith(tuple(p.lower() for p in prefixes))


@dataclass(frozen=True)
class Lane:
    """One worktree's lane and the repo-relative path prefixes it may change."""

    name: str                                        # "main" when the worktree has no .lane file
    owned: tuple[str, ...] | None = None             # None: every path (lane main)
    shared: tuple[str, ...] = ()
    lanes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    error: str = ""                                  # non-empty: every edit is blocked

    @property
    def is_main(self) -> bool:
        return self.owned is None

    @property
    def handoff(self) -> str:
        return "HANDOFF.md" if self.is_main else f"docs/handoff/{self.name}.md"

    def allows(self, rel: str) -> bool:
        """True when this lane may change the repo-relative POSIX path `rel`."""
        if self.error:
            return False
        return self.owned is None or starts_with(rel, self.owned + self.shared)

    def owner(self, rel: str) -> str:
        """The lane whose prefixes cover `rel`, or "main" when no lane lists it."""
        return next((name for name, prefixes in self.lanes.items() if starts_with(rel, prefixes)), MAIN)


def load_lane(root: Path) -> Lane:
    """The lane of the worktree at `root`: the word in its .lane file, looked up in lanes.json."""
    try:
        word = (root / LANE_FILE).read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError:
        return Lane(MAIN)
    except (OSError, ValueError):
        return Lane("?", owned=(), error=f"{LANE_FILE} cannot be read")
    config = _load_lanes_file(root)
    if isinstance(config, str):
        return Lane(word, owned=(), error=f"{LANE_FILE} says '{word}' but {LANES_FILE} {config}")
    shared, lanes = config
    if word not in lanes:
        return Lane(word, owned=(), shared=shared, lanes=lanes,
                    error=f"unknown lane '{word}' in {LANE_FILE} (lanes in {LANES_FILE}: {', '.join(lanes)})")
    return Lane(word, owned=lanes[word], shared=shared, lanes=lanes)


def _load_lanes_file(root: Path) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]] | str:
    """(shared prefixes, {lane: prefixes}), or a short phrase saying why the file is unusable.
    Keys that start with "_" (such as "_comment") are ignored."""
    try:
        with (root / LANES_FILE).open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return "is missing"
    except json.JSONDecodeError as exc:
        return f"is not valid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"
    except (OSError, ValueError) as exc:
        return f"cannot be read ({exc.__class__.__name__})"
    lanes = raw.get("lanes") if isinstance(raw, dict) else None
    names = [name for name in lanes if not name.startswith("_")] if isinstance(lanes, dict) else []
    if not names:
        return 'has no lanes under "lanes"'
    try:
        shared = _prefixes(raw.get("shared", {"paths": []}), "shared")
        return shared, {name: _prefixes(lanes[name], f"lanes.{name}") for name in names}
    except ValueError as exc:
        return str(exc)


def _prefixes(table: object, where: str) -> tuple[str, ...]:
    paths = table.get("paths") if isinstance(table, dict) else None
    if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
        raise ValueError(f'needs "paths": ["prefix", ...] under {where}')
    return tuple(paths)
