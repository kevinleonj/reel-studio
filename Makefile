# Reel Studio. Written for GNU make 3.81, the macOS default: no .ONESHELL, no $(file ...),
# no grouped targets (&:). Each recipe line is its own shell; keep logic in Python scripts.

.DEFAULT_GOAL := help

UV := uv run --locked --all-extras
PY313 := uv run --quiet --no-project --python 3.13 python
FAST := not paid and not slow and not race and not e2e and not emulator
GITLEAKS_TIMEOUT_S := 300

.PHONY: help sync setup test-fast test lint types guardrails ci

help:
	@echo "make setup      install dependencies and pre-commit, create .env from .env.example"
	@echo "make test-fast  unit tests (< 60 s)"
	@echo "make test       every test except paid ones"
	@echo "make lint       ruff format --check and ruff check"
	@echo "make types      mypy (strict)"
	@echo "make ci         everything CI runs; stamps .ci-pass on a clean tree"

# Every extra, so ruff, mypy and pytest come from uv.lock and never from a global install.
sync:
	uv sync --locked --all-extras

setup: sync
	$(UV) pre-commit install
	@test -f .env || cp .env.example .env

test-fast:
	$(UV) pytest -q -m "$(FAST)"

test:
	$(UV) pytest -q -m "not paid"

lint:
	$(UV) ruff format --check .
	$(UV) ruff check .

types:
	$(UV) mypy

# The repository's own guardrails: hook self-check, hard-coded value scanner, gate engine,
# and a secret scan of the whole history.
guardrails:
	python3 .claude/hooks/selfcheck.py
	$(PY313) scripts/check_literals.py
	python3 scripts/gates/_gate.py --self-test
	@command -v gitleaks >/dev/null || { echo "gitleaks not found: brew install gitleaks (README)"; exit 1; }
	gitleaks git --redact --no-banner --timeout $(GITLEAKS_TIMEOUT_S) .

ci: sync lint types test guardrails ci-engine ci-web ci-cloud
	python3 scripts/ci_stamp.py

# Each lane fills its own ci-<lane> target (docs/build/README.md).
include mk/engine.mk mk/web.mk mk/cloud.mk
