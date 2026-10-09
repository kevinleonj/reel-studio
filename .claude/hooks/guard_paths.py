#!/usr/bin/env python3
"""PreToolUse guard for Edit, Write, MultiEdit and NotebookEdit (F54).

Exit 2 blocks the edit; stderr explains why. Overrides are environment variables Kevin
sets when he starts a session on purpose; Claude Code cannot set them for itself.
Lane ownership: a worktree with a .lane file may edit only its lane's paths in
.claude/lanes.json plus the shared ones; no .lane file means lane main (every path).
Paths are compared in lowercase: the default macOS file system treats Docs/ as docs/.
Python 3.9+ standard library only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn

sys.dont_write_bytecode = True                      # importing _common must leave no __pycache__ here
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

WORKFLOWS = {".github/workflows/ci.yml", ".github/workflows/deploy.yml"}
LITERAL_GUARDS = {"scripts/check_literals.py", "tests/literal_allowlist.toml"}
GIT_GUARDS = {(".git", "hooks"), (".git", "config")}


def block(reason: str) -> NoReturn:
    sys.stderr.write(f"Blocked by .claude/hooks/guard_paths.py: {reason}\n")
    sys.exit(2)


def main() -> None:
    data = _common.read_input(sys.stdin)
    if data is None:
        block("Hook input was not JSON.")
    tool_input = _common.tool_input(data)
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not raw:
        sys.exit(0)
    root = _common.repo_root(data)
    path = Path(raw)
    if not path.is_absolute():
        path = (Path(data.get("cwd") or root) / path)
    path = path.resolve()

    if not (path == root or root in path.parents):
        if _common.inside(path, _common.temp_roots()):
            sys.exit(0)
        block(f"Writes outside the repository are not allowed: {path}")

    rel = PurePosixPath(path.relative_to(root).as_posix())
    low = str(rel).lower()                               # Docs/DECISIONS.md is docs/DECISIONS.md on a Mac
    parts = tuple(part.lower() for part in rel.parts)
    name = parts[-1] if parts else ""
    lane = _common.load_lane(root)

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        block("Never edit .env files. Kevin edits secrets himself.")
    if name.endswith(".tfstate") or name.endswith(".tfstate.backup") or ".terraform" in parts or name == "tfplan":
        block("Terraform state and plans are never edited by hand.")
    if name in {"uv.lock", "package-lock.json"}:
        block("Lock files change only through `uv add` / `uv lock` or `npm install`.")
    if low == "docs/decisions.md" and os.environ.get("REEL_ALLOW_DECISION_EDIT") != "1":
        block(f"docs/DECISIONS.md is locked. Write the conflict under 'Needs Kevin' in {lane.handoff}.")
    if parts[:2] == ("tests", "golden") and os.environ.get("REEL_ALLOW_GOLDEN") != "1":
        block("Golden files are locked. Fix the code, or ask Kevin to approve a new golden file.")
    if name == ".ci-pass":
        block("Only `make ci` writes .ci-pass.")
    if parts[:2] in GIT_GUARDS:
        block(".git/hooks/ and .git/config are not edited from a session: they run or switch off gitleaks.")
    if parts[:2] == (".github", "workflows") and low not in WORKFLOWS:
        block("No new workflow files: CI is one ci.yml calling make ci; deploy is deploy.yml.")
    if parts[:2] == ("scripts", "gates") and os.environ.get("REEL_ALLOW_GATE_EDIT") != "1":
        block("scripts/gates/ holds the CI gates; they change only with REEL_ALLOW_GATE_EDIT=1. Ask Kevin.")
    if low in LITERAL_GUARDS and os.environ.get("REEL_ALLOW_LITERAL_EDIT") != "1":
        block(f"{rel} changes only with REEL_ALLOW_LITERAL_EDIT=1. "
              "Write the entry you need, with its reason, under 'Needs Kevin'.")
    guardrail = parts[:2] in {(".claude", "hooks"), (".claude", "agents")} or low == _common.LANE_FILE or \
        (len(parts) == 2 and parts[0] == ".claude" and (name.startswith("settings") or name == "lanes.json"))
    if guardrail and os.environ.get("REEL_ALLOW_HOOK_EDIT") != "1":
        block("The guardrails are not edited from inside a session. Ask Kevin.")
    text = json.dumps(tool_input)
    if "disableAllHooks" in text:
        block("Hooks may not be switched off from a session.")

    if lane.error:
        block(f"{lane.error}. Every edit is blocked until Kevin fixes .lane or {_common.LANES_FILE}.")
    if not lane.allows(str(rel)):
        block(f"{rel} belongs to lane '{lane.owner(str(rel))}', not to this worktree's lane '{lane.name}'. "
              f"Write what you need under 'Needs Kevin' in {lane.handoff} and continue with your own files.")
    sys.exit(0)


if __name__ == "__main__":
    main()
