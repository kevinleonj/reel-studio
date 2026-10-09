#!/usr/bin/env python3
"""Gate for docs/build/STEP-08.md: the Google Cloud beta (Tier 2).

    python3 scripts/gates/step08.py [--local]

_gate.main adds the five checks every gate runs (make ci and .ci-pass, literal scan,
no Agent SDK, handoff file, pull request with green CI). --local skips the GitHub ones.
SITE_URL is the only line read from .env, and the only value this gate may print.
"""

import importlib
import os
import sys

sys.dont_write_bytecode = True  # a gate never writes into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
g = importlib.import_module("_gate")

DEPLOY_YML = ".github/workflows/deploy.yml"

CHECKS = [
    g.command(g.uv("python", "scripts/check_policy.py")),
    g.workflows("ci.yml", "deploy.yml"),
    g.contains(DEPLOY_YML, "environment:", "cancel-in-progress: false"),
    g.smoke_from_env(),
    g.line_starting("docs/handoff/cloud.md", "Phone order:"),
]

if __name__ == "__main__":
    g.main("08", CHECKS)
