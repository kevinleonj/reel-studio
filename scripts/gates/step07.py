#!/usr/bin/env python3
"""Gate for docs/build/STEP-07.md: Stripe gate, weekly limit, two slots and the queue.

    python3 scripts/gates/step07.py [--local]

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
    g.pytest_passed(["-m", "race"], minimum=4),
    g.command(g.uv("reelctl", "--help")),
    g.output_has(g.uv("reelctl", "codes", "create", "--help"), "--expires"),
    g.line_starting("docs/handoff/web.md", "Stripe e2e order:"),
]

if __name__ == "__main__":
    g.main("07", CHECKS)
