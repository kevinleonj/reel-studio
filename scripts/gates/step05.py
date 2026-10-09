#!/usr/bin/env python3
"""Gate for docs/build/STEP-05.md: speech (long takes, talking clips, tutorials).

    python3 scripts/gates/step05.py [--local]

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
    g.exists("eval/SPEECH-RESULT.md"),
    g.speech_evals("long_take", "talking", "tutorial", model="sonnet"),
    g.results_budget("10.00"),
]

if __name__ == "__main__":
    g.main("05", CHECKS)
