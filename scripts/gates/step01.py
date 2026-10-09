#!/usr/bin/env python3
"""Gate for docs/build/STEP-01.md: skeleton, guardrails, CI.

    python3 scripts/gates/step01.py [--local]

_gate.main adds the five checks every gate runs (make ci and .ci-pass, literal scan,
no Agent SDK, handoff file, pull request with green CI). --local skips the GitHub ones.
"""

import importlib
import os
import sys

sys.dont_write_bytecode = True  # a gate never writes into the repository
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
g = importlib.import_module("_gate")

FILES = (
    "LICENSE",
    "README.md",
    "SECURITY.md",
    ".gitignore",
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    "mk/engine.mk",
    "mk/web.mk",
    "mk/cloud.mk",
    ".pre-commit-config.yaml",
    ".github/workflows/ci.yml",
    "scripts/ci-install.sh",
    "reel_studio/settings.py",
    "reel_studio/core/config.py",
    "reel_studio/core/constants.py",
    "reel_studio/core/ports.py",
    "reel_studio/core/errors.py",
    "reel_studio/core/logging.py",
    "reel_studio/adapters/clock.py",
    "tests/conftest.py",
    "tests/unit/test_isolation.py",
    "docs/handoff/engine.md",
    "docs/handoff/web.md",
    "docs/handoff/cloud.md",
)
IGNORED = (
    ".env",
    ".lane",
    ".ci-pass",
    ".DS_Store",
    "__pycache__/",
    "node_modules/",
    ".venv/",
    "out/",
    "data/",
)
CI_YML = ".github/workflows/ci.yml"
MAKE_TARGETS = ("make", "-n", "setup", "test-fast", "test", "lint", "types", "ci")

CHECKS = [
    g.exists(*FILES),
    g.contains("LICENSE", "MIT"),
    g.has_lines(".gitignore", *IGNORED),
    g.workflows("ci.yml"),
    g.contains(CI_YML, "make ci", "timeout-minutes", "concurrency", "contents: read"),
    g.actions_pinned(CI_YML),
    g.contains(".pre-commit-config.yaml", "gitleaks", "language: system"),
    g.command(MAKE_TARGETS),
    g.command(("python3", ".claude/hooks/selfcheck.py")),
    g.command((*g.LITERAL_SCAN, "--self-test")),
    g.pytest_markers("paid", "slow", "race", "e2e", "emulator"),
    # one test proves unit tests cannot open a network connection, one that Settings
    # ignore the .env file in tests
    g.pytest_passed(["tests/unit/test_isolation.py"], minimum=2),
    g.ruleset(),
]

if __name__ == "__main__":
    g.main("01", CHECKS)
