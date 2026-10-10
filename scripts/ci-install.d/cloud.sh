#!/usr/bin/env bash
# Lane cloud owns this file: CI tools its steps need (Terraform, tflint, Trivy in STEP-08).
# Run by scripts/ci-install.sh, which already put ~/.local/bin on PATH. Linux x86-64 only; each
# download is pinned and checksum-verified (FACTS F403, F404, F405).
set -euo pipefail

TERRAFORM_VERSION="1.16.5"  # D60, F36
TERRAFORM_SHA256="2bc2fcfff033265c9e02ca0351f01794eb122f62a9b2a49a3294b9e49eaab5e4"  # F405
TERRAFORM_URL="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"  # hardcode-ok: named constant, pinned release
TFLINT_VERSION="0.64.0"  # F404
TFLINT_SHA256="cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537"  # F405
TFLINT_URL="https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_amd64.zip"  # hardcode-ok: named constant, pinned release
GOOGLE_RULESET_VERSION="0.40.0"  # F404, must equal infra/.tflint.hcl
GOOGLE_RULESET_SHA256="a5c02b3de937456de2521155831eaf1cc876014a21445bf7dd1621654511fe28"  # F405
GOOGLE_RULESET_URL="https://github.com/terraform-linters/tflint-ruleset-google/releases/download/v${GOOGLE_RULESET_VERSION}/tflint-ruleset-google_linux_amd64.zip"  # hardcode-ok: named constant, pinned release
TRIVY_VERSION="0.74.0"  # F404
TRIVY_SHA256="2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a"  # F405
TRIVY_URL="https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"  # hardcode-ok: named constant, pinned release
DOWNLOAD_RETRIES=3
DOWNLOAD_TIMEOUT_S=300

BIN="${HOME}/.local/bin"
# tflint's default plugin directory. Installing the ruleset here directly avoids `tflint --init`,
# which calls the rate-limited GitHub API from a shared runner address.
PLUGIN_DIR="${HOME}/.tflint.d/plugins/github.com/terraform-linters/tflint-ruleset-google/${GOOGLE_RULESET_VERSION}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${BIN}" "${PLUGIN_DIR}"

fetch() { # fetch <url> <sha256> <file>
  curl --fail --silent --show-error --location \
    --retry "${DOWNLOAD_RETRIES}" --max-time "${DOWNLOAD_TIMEOUT_S}" -o "${WORK}/$3" "$1"
  echo "$2  ${WORK}/$3" | sha256sum --check --strict -
}

fetch "${TERRAFORM_URL}" "${TERRAFORM_SHA256}" terraform.zip
unzip -q -o "${WORK}/terraform.zip" terraform -d "${WORK}"
install -m 0755 "${WORK}/terraform" "${BIN}/"

fetch "${TFLINT_URL}" "${TFLINT_SHA256}" tflint.zip
unzip -q -o "${WORK}/tflint.zip" tflint -d "${WORK}"
install -m 0755 "${WORK}/tflint" "${BIN}/"

fetch "${GOOGLE_RULESET_URL}" "${GOOGLE_RULESET_SHA256}" ruleset.zip
unzip -q -o "${WORK}/ruleset.zip" tflint-ruleset-google -d "${WORK}"
install -m 0755 "${WORK}/tflint-ruleset-google" "${PLUGIN_DIR}/"

fetch "${TRIVY_URL}" "${TRIVY_SHA256}" trivy.tar.gz
tar -xzf "${WORK}/trivy.tar.gz" -C "${WORK}" trivy
install -m 0755 "${WORK}/trivy" "${BIN}/"

# sed reads its whole input; `head -1` would close the pipe early and, under pipefail, turn the
# writer's SIGPIPE into exit 141.
terraform version | sed -n 1p
tflint --version | sed -n 1p
trivy --version | sed -n 1p
