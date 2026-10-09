#!/usr/bin/env python3
"""Gate for docs/build/STEP-03.md: the editor loop, `reel make` with Claude.

    python3 scripts/gates/step03.py [--local]

_gate.main adds the five checks every gate runs (make ci and .ci-pass, literal scan,
no Agent SDK, handoff file, pull request with green CI). --local skips the GitHub ones.
Evidence comes from make eval: eval/results/<YYYY-MM-DD>/<fixture>-<model>.json.
"""

import importlib
import os
import sys

sys.dont_write_bytecode = True  # a gate never writes into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
g = importlib.import_module("_gate")

CHECKS = [
    g.command(g.uv("reel", "make", "--help")),
    g.pytest_passed(["tests/unit/editor", "-m", "not paid"], minimum=25),
    g.eval_evidence("creami", model="sonnet", max_cost="1.20", cheaper="haiku"),
    g.results_budget("5.00"),
]

if __name__ == "__main__":
    g.main("03", CHECKS)
