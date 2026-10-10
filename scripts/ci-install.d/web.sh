#!/usr/bin/env bash
# Lane web owns this file: CI tools its steps need. Run by scripts/ci-install.sh.
# make ci needs only Node (installed by ci-install.sh) and npm ci, which ci-web runs itself.
# Playwright's Chromium is for `make prerelease` only (STEP-06 task 5): set REEL_PRERELEASE=1.
set -euo pipefail

if [ "${REEL_PRERELEASE:-}" = "1" ]; then
  npm --prefix web ci
  (cd web && npx playwright install --with-deps chromium)
fi
