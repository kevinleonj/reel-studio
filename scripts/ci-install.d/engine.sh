#!/usr/bin/env bash
# Lane engine owns this file: CI tools its steps need. Run by scripts/ci-install.sh.
set -euo pipefail

# scripts/ci-install.sh installs Ubuntu's ffmpeg, built with libzimg (F201). The media tests need
# zscale, so a build without it fails the install step, not a test ten minutes later.
ffmpeg -hide_banner -filters | grep -q ' zscale '
