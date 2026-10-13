# Lane cloud owns this file (STEP-08). Included by the Makefile, which defines UV.
# Tools come from PATH: scripts/ci-install.d/cloud.sh in CI, Homebrew on the Mac (versions in
# FACTS F404). Override per run, e.g. `make ci TERRAFORM=/path/to/terraform`.

TERRAFORM ?= terraform
TFLINT ?= tflint
TRIVY ?= trivy
TF_ROOTS := infra/bootstrap infra/main
# Findings below HIGH are known and by design (docs/handoff/cloud.md: GCP-0078, GCP-0066).
TRIVY_SEVERITY := HIGH,CRITICAL

.PHONY: ci-cloud policy tf-fmt tf-validate tf-test tflint tflint-init trivy \
	gcp-project bootstrap-plan secrets-push stripe-setup dns smoke spend-cap spend-cap-lift github-env

ci-cloud: policy tf-fmt tf-validate tf-test tflint trivy

policy:
	$(UV) python scripts/check_policy.py

tf-fmt:
	$(TERRAFORM) fmt -check -recursive infra

# -backend=false: validation needs no state; -lockfile=readonly: the committed lock is the truth.
tf-validate:
	for root in $(TF_ROOTS); do \
		$(TERRAFORM) -chdir=$$root init -backend=false -input=false -lockfile=readonly >/dev/null && \
		$(TERRAFORM) -chdir=$$root validate -no-color || exit 1; \
	done

# Offline: mock_provider, no project, no credentials (infra/*/tests/).
tf-test: tf-validate
	for root in $(TF_ROOTS); do \
		$(TERRAFORM) -chdir=$$root test -no-color || exit 1; \
	done

# The google ruleset must be installed first: cloud.sh does it in CI, `make tflint-init` on a laptop.
tflint:
	$(TFLINT) --chdir infra --recursive --config "$(CURDIR)/infra/.tflint.hcl" --format compact

tflint-init:
	$(TFLINT) --chdir infra --recursive --init --config "$(CURDIR)/infra/.tflint.hcl"

# --skip-check-update: the checks embedded in the pinned Trivy, so a run never changes under us.
trivy:
	$(TRIVY) config --quiet --skip-check-update --exit-code 1 --severity $(TRIVY_SEVERITY) infra

# ---- STEP-08 setup by API (docs/INFRA.md §3). Each reads .env itself and never prints a value.

gcp-project:
	$(UV) python scripts/cloud/gcp_project.py

bootstrap-plan:
	$(UV) python scripts/cloud/bootstrap_plan.py

secrets-push:
	$(UV) python scripts/cloud/secrets_push.py

stripe-setup:
	@test -n "$(MODE)" || { echo "usage: make stripe-setup MODE=test|live"; exit 2; }
	$(UV) python scripts/cloud/stripe_setup.py --mode "$(MODE)"

dns:
	$(UV) python scripts/cloud/dns.py

smoke:
	@test -n "$(URL)" || { echo "usage: make smoke URL=<service url>"; exit 2; }
	$(UV) python scripts/smoke.py --url "$(URL)"

# Hard stop on one service's monthly bill (F414). Optional: PROJECT=<id> SERVICE=services/XXXX-XXXX-XXXX.
SPEND_CAP_ARGS = $(if $(PROJECT),--project "$(PROJECT)") $(if $(SERVICE),--service "$(SERVICE)")

spend-cap:
	$(UV) python scripts/cloud/spend_cap.py $(SPEND_CAP_ARGS)

# Asks for the project id to be typed back before lifting an enforced cap.
spend-cap-lift:
	$(UV) python scripts/cloud/spend_cap.py --lift $(SPEND_CAP_ARGS)

# The beta approval gate as code: owner as only reviewer, deploys from main only (F417).
github-env:
	$(UV) python scripts/cloud/github_env.py
