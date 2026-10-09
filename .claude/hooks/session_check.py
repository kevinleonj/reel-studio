#!/usr/bin/env python3
"""SessionStart hook (startup, resume, clear, compact): short context lines for Claude.

Claude Code adds a SessionStart hook's plain stdout to Claude's context. This hook warns when the
operating system is neither macOS nor Linux, when the Python running the hooks is older than 3.9,
or when ANTHROPIC_API_KEY is exported (presence only; the value is never read or printed), then
names the worktree's lane and its paths. It never blocks and always exits 0.

Deliberately plain: no annotations, no `from __future__`, `_common` imported late, so even a
python3 too old for the other hooks gets far enough to print the warning.
"""

import os
import platform
import sys

sys.dont_write_bytecode = True                      # importing _common must leave no __pycache__ here
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIN_PYTHON = (3, 9)
SYSTEMS = ("Darwin", "Linux")
API_KEY = ("WARNING: ANTHROPIC_API_KEY is exported in this shell; Claude Code may bill that key instead of "
           "the Max plan. The app reads .env itself; unset it and restart.")


def system_line():
    system = platform.system()
    if system in SYSTEMS:
        return None
    return ("WARNING: unsupported operating system ({0}); the hooks expect macOS or Linux. "
            "Stop and tell Kevin.").format(system or "unknown")


def python_line():
    if tuple(sys.version_info[:2]) >= MIN_PYTHON:
        return None
    version = ".".join(str(part) for part in sys.version_info[:3])
    return ("WARNING: python3 is {0}, older than the 3.9 the hooks are tested on; a guard that crashes "
            "blocks the call. Tell Kevin to put a newer python3 first on PATH (uv python install 3.13)."
            ).format(version)


def lane_lines(common, root):
    lane = common.load_lane(root)
    if lane.error:
        return ["WARNING: {0}. Every edit is blocked. Stop and tell Kevin.".format(lane.error)]
    if lane.owned is None:
        return ["Lane: main (all paths)"]
    return ["Lane: {0} (owned paths: {1})".format(lane.name, ", ".join(lane.owned)),
            "Shared paths every lane may edit: {0}".format(", ".join(lane.shared) or "none"),
            "Handoff file for this lane: {0} (write blockers under 'Needs Kevin').".format(lane.handoff)]


def main():
    lines = []
    try:
        for line in (system_line(), python_line()):
            if line:
                lines.append(line)
        if "ANTHROPIC_API_KEY" in os.environ:        # presence only, never the value
            lines.append(API_KEY)
        import _common                               # late: a too-old Python still printed the warnings
        data = _common.read_input(sys.stdin) or {}
        lines.extend(lane_lines(_common, _common.repo_root(data)))
    except Exception as exc:  # noqa: BLE001 - a session must start even if this check breaks
        lines.append("WARNING: .claude/hooks/session_check.py failed ({0}); lane unknown.".format(
            exc.__class__.__name__))
    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    main()
