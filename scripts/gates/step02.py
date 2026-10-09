#!/usr/bin/env python3
"""Gate for docs/build/STEP-02.md: render a Reel from a hand-written edit list.

    python3 scripts/gates/step02.py [--local]

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
    g.command(g.uv("reel", "render", "--help")),
    # The output spec is written here on purpose, not read from config: it is the locked
    # spec (docs/DECISIONS.md D42 audio at -14 LUFS, D43 files 1080x1920, 30 fps, H.264,
    # AAC), so a changed config file cannot move the gate.
    g.render_roundtrip(
        "tests/fixtures/edl/basic.json",
        min_clips=5,
        width=1080,
        height=1920,
        fps="30/1",
        video="h264",
        audio="aac",
        lufs=-14,
        tolerance=1.0,
    ),
]

if __name__ == "__main__":
    g.main("02", CHECKS)
