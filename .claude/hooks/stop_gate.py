#!/usr/bin/env python3
"""Stop hook (F54): Claude may not end a turn with changes outside its lane, or with red fast
tests after changing code. Python 3.9+ standard library only.

1. Lane check (every lane except main): files changed on the branch since the merge base with
   origin/main (else main), plus uncommitted and untracked files, must lie inside the lane's
   paths or the shared ones in .claude/lanes.json (compared in lowercase, as macOS does).
2. Runs `make test-fast` only when code files changed and the Makefile has that target.
Respects `stop_hook_active` so it never loops on a problem it cannot fix.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

sys.dont_write_bytecode = True                      # importing _common must leave no __pycache__ here
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

CODE_SUFFIXES = (".py", ".ts", ".tsx", ".tf", ".toml", ".j2", ".md")
CODE_DIRS = ("reel_studio/", "web/src/", "infra/", "config/", "tests/")
BASE_REFS = ("origin/main", "main")
MAX_LISTED = 30


def git_out(root: Path, *args: str) -> str:
    return _common.git(root, *args).stdout


def merge_base(root: Path) -> tuple[str, str] | None:
    """(ref, commit) of `git merge-base HEAD origin/main`, else of main; None when neither exists."""
    for ref in BASE_REFS:
        found = _common.git(root, "merge-base", "HEAD", ref)
        if found.returncode == 0 and found.stdout.strip():
            return ref, found.stdout.strip()
    return None


def uncommitted(root: Path) -> list[str]:
    """Modified, staged, deleted and untracked paths; a rename counts as both of its paths."""
    out = git_out(root, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    return [entry[3:] for entry in out.split("\0") if len(entry) > 3]


def committed(root: Path, base: str) -> list[str]:
    """Paths changed by the commits between the merge base and HEAD."""
    out = git_out(root, "diff", "--name-only", "--no-renames", "-z", f"{base}..HEAD")
    return [p for p in out.split("\0") if p]


def ci_passed(root: Path, head: str) -> bool:
    """True when `make ci` stamped this exact commit, so committed files need no re-test."""
    try:
        stamp = root / ".ci-pass"
        return bool(head) and stamp.exists() and stamp.read_text().strip() == head
    except OSError:
        return False


def counted(path: str) -> bool:
    """The lane marker itself and Finder's .DS_Store files are never a lane's change."""
    return path.lower() != _common.LANE_FILE and os.path.basename(path).lower() != ".ds_store"


def block(reason: str) -> NoReturn:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def check_lane(lane: _common.Lane, changed: list[str], base: tuple[str, str] | None) -> None:
    outside = sorted({p for p in changed if counted(p) and not lane.allows(p)})
    if not outside:
        return
    listed = outside[:MAX_LISTED] + ([f"... and {len(outside) - MAX_LISTED} more"] if len(outside) > MAX_LISTED else [])
    since = f"{base[0]} (merge base {base[1][:12]})" if base else "the last commit (no origin/main or main to compare)"
    if lane.error:
        head = f"{lane.error}, so every change in this worktree is outside the lane:"
        tail = "Stop and tell Kevin."
    else:
        head = f"This worktree is lane '{lane.name}'; these paths changed since {since} belong to other lanes:"
        tail = (f"Revert them (restore each path to its version at the merge base, delete files you added), "
                f"or move the need to 'Needs Kevin' in {lane.handoff}.")
    block("\n".join([head, *[f"  {p}" for p in listed], tail]))


def main() -> None:
    data = _common.read_input(sys.stdin)
    if data is None:
        sys.exit(0)
    if data.get("stop_hook_active"):
        sys.exit(0)
    root = _common.repo_root(data)
    lane = _common.load_lane(root)
    try:
        head = git_out(root, "rev-parse", "HEAD").strip()
        local = uncommitted(root)
        base = merge_base(root)
        branch = committed(root, base[1]) if base and base[1] != head else []
    except (OSError, subprocess.SubprocessError):
        sys.exit(0)
    if not lane.is_main:
        check_lane(lane, local + branch, base)

    makefile = root / "Makefile"
    if not makefile.exists() or not re.search(r"^test-fast:", makefile.read_text(), re.M):
        sys.exit(0)
    changed = local + ([] if ci_passed(root, head) else branch)
    code = [p for p in changed if p.lower().startswith(CODE_DIRS) and p.lower().endswith(CODE_SUFFIXES)]
    if not code:
        sys.exit(0)
    try:
        run = subprocess.run(["make", "test-fast"], cwd=root, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        block("make test-fast took longer than 300 s. Keep fast tests fast, then finish.")
    except OSError:
        sys.exit(0)
    if run.returncode != 0:
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-40:])
        block("make test-fast is red. Fix it before stopping, or write it under "
              f"'Needs Kevin' in {lane.handoff} if you cannot.\n{tail}")
    if lane.handoff.lower() not in {p.lower() for p in changed}:
        reminder = f"Code changed but {lane.handoff} did not. Update it before you finish."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reminder}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
