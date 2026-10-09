#!/usr/bin/env python3
"""Gate for docs/build/STEP-09.md: the friends beta.

    python3 scripts/gates/step09.py [--local]

_gate.main adds the five checks every gate runs (make ci and .ci-pass, literal scan,
no Agent SDK, handoff file, pull request with green CI). --local skips the GitHub ones.
"""

import importlib
import os
import sys

sys.dont_write_bytecode = True  # a gate never writes into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
g = importlib.import_module("_gate")

CHECKS = [
    g.command(g.uv("reelctl", "report", "--week")),
    g.contains("HANDOFF.md", "Weekly report"),
]

if __name__ == "__main__":
    g.main("09", CHECKS)
