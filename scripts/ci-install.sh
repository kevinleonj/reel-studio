#!/usr/bin/env bash
# Installs the CI tools on GitHub's ubuntu-24.04 runner, each pinned and checksum-verified,
# then runs every lane's scripts/ci-install.d/*.sh. Linux x86-64 only; the Mac uses brew (STEP-00).
set -euo pipefail

UV_VERSION="0.12.24"        # docs/FACTS.md F39
UV_SHA256="b4dfaef47d491a7296981f8374a4595f55dbf84e8937c8ecd2983574d8bb3da6"        # F76
UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"  # hardcode-ok: named constant, pinned release
NODE_VERSION="24.21.0"      # F41
NODE_SHA256="fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6"      # F77
NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"  # hardcode-ok: named constant, pinned release
GITLEAKS_VERSION="8.30.1"   # F44
GITLEAKS_SHA256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"  # F44
GITLEAKS_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"  # hardcode-ok: named constant, pinned release
DOWNLOAD_RETRIES=3
DOWNLOAD_TIMEOUT_S=300

BIN="${HOME}/.local/bin"
NODE_HOME="${HOME}/.local/node"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${BIN}" "${NODE_HOME}"

fetch() { # fetch <url> <sha256> <file>
  curl --fail --silent --show-error --location \
    --retry "${DOWNLOAD_RETRIES}" --max-time "${DOWNLOAD_TIMEOUT_S}" -o "${WORK}/$3" "$1"
  echo "$2  ${WORK}/$3" | sha256sum --check --strict -
}

fetch "${UV_URL}" "${UV_SHA256}" uv.tar.gz
tar -xzf "${WORK}/uv.tar.gz" -C "${WORK}"
install -m 0755 "${WORK}/uv-x86_64-unknown-linux-gnu/uv" "${WORK}/uv-x86_64-unknown-linux-gnu/uvx" "${BIN}/"

fetch "${NODE_URL}" "${NODE_SHA256}" node.tar.xz
tar -xJf "${WORK}/node.tar.xz" -C "${NODE_HOME}" --strip-components=1

fetch "${GITLEAKS_URL}" "${GITLEAKS_SHA256}" gitleaks.tar.gz
tar -xzf "${WORK}/gitleaks.tar.gz" -C "${WORK}" gitleaks
install -m 0755 "${WORK}/gitleaks" "${BIN}/"

sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends ffmpeg

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "${BIN}" >> "${GITHUB_PATH}"
  echo "${NODE_HOME}/bin" >> "${GITHUB_PATH}"
fi
export PATH="${BIN}:${NODE_HOME}/bin:${PATH}"

for lane in scripts/ci-install.d/*.sh; do
  bash "${lane}"
done

uv --version
node --version
gitleaks version
ffmpeg -hide_banner -version | head -1
