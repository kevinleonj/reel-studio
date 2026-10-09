#!/usr/bin/env python3
"""Gate for docs/build/STEP-04.md: the A/B of the new engine against the old kit.

    python3 scripts/gates/step04.py [--local]

_gate.main adds the five checks every gate runs (make ci and .ci-pass, literal scan,
no Agent SDK, handoff file, pull request with green CI). --local skips the GitHub ones.
Every A/B rule is recomputed from the newest eval/results/<YYYY-MM-DD>/ab.json; no
verdict written in the file is trusted.
"""

import importlib
import os
import sys

sys.dont_write_bytecode = True  # a gate never writes into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
g = importlib.import_module("_gate")

CHECKS = [
    g.exists("eval/AB-RESULT.md"),
    # docs/EDITOR.md section 11, and the step's paid budget
    g.ab_gate(fixtures=5, min_new_or_tie=3, critic_margin=1, max_mean_cost="1.20", budget="15.00"),
]

if __name__ == "__main__":
    g.main("04", CHECKS)
