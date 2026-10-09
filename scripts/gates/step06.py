#!/usr/bin/env python3
"""Gate for docs/build/STEP-06.md: the website on the laptop (Tier 1).

    python3 scripts/gates/step06.py [--local]

_gate.main adds the five checks every gate runs (make ci and .ci-pass, literal scan,
no Agent SDK, handoff file, pull request with green CI). --local skips the GitHub ones.
The live-site check runs `make up` and always `make down` at the end.
"""

import importlib
import os
import sys

sys.dont_write_bytecode = True  # a gate never writes into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
g = importlib.import_module("_gate")

SITE = "http://localhost:8080"
PAGES = (
    g.Page(
        "/",
        html_has=("<h1", "<title>", '<meta name="description"'),
        html_lacks=("noindex", "googletagmanager.com"),
    ),
    g.Page("/privacy"),
    g.Page("/new", noindex_header=True),
    g.Page("/o/gate-check", noindex_header=True),
)

CHECKS = [
    g.command(("make", "prerelease"), timeout=g.TIMEOUT_LONG),
    g.live_site(
        SITE,
        PAGES,
        # a noindex page must stay crawlable, or crawlers never see the noindex
        crawlable=("/o/gate-check", "/new"),
        config_false=("analytics", "enabled"),
    ),
    g.line_starting("docs/handoff/web.md", "iPhone upload:"),
]

if __name__ == "__main__":
    g.main("06", CHECKS)
