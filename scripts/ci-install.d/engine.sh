#!/usr/bin/env bash
# Lane engine owns this file: CI tools its steps need. Run by scripts/ci-install.sh.
set -euo pipefail

# ffmpeg for the media tests. Ubuntu builds it with libzimg, so zscale is there (F201); the
# check makes a missing filter fail the install step, not a test ten minutes later.
APT_TIMEOUT_S=60   # per HTTP request
APT_RETRIES=3
APT=(-o "Acquire::http::Timeout=${APT_TIMEOUT_S}" -o "Acquire::Retries=${APT_RETRIES}")
sudo apt-get "${APT[@]}" update -q
sudo apt-get "${APT[@]}" install -y -q --no-install-recommends ffmpeg
ffmpeg -hide_banner -filters | grep -q ' zscale '
