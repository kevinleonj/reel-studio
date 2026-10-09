# STEP-01 — Skeleton, guardrails, CI (lane main, runs alone)

**Outcome:** anyone can clone the repository, run `make setup` and `make ci`, and see it pass; the hooks,
the hard-coded-value scanner and the gates are wired in; the three lanes can start as soon as this merges.
No product behaviour in this step: one session, keep it small.

Repository: the main checkout (`git rev-parse --show-toplevel` ends in `/reel/reel-studio`). Do not leave it.
Settled, do not re-ask: D06 (MIT), D61, D70, D72–D78. Paid budget: $0.
**Gate:** `python3 scripts/gates/step01.py` prints `GATE step01 PASS`.

## Discovery (stop and report if anything differs)

```bash
git rev-parse --show-toplevel                    # ends with /reel/reel-studio
git status --short                               # empty
uv --version && python3 --version                # uv ≥ 0.12, python3 ≥ 3.9 (hooks); Node 24 only from STEP-06
grep -o '^[A-Z_]*=' .env | sort                  # names only; ANTHROPIC_API_KEY= present
python3 .claude/hooks/selfcheck.py | tail -1     # PASS: 465 checks
```
Create branch `step-01-skeleton`.

## Tasks (each: failing test first, then code, then `make test-fast`)

1. **Package with every dependency up front.** Lanes do not edit `pyproject.toml` later, so declare now:
   base `pydantic`, `pydantic-settings`, `jinja2`; `[editor]` `anthropic`, `google-genai`, `pillow`;
   `[api]` `fastapi`, `uvicorn[standard]`, `google-cloud-firestore`, `google-cloud-storage`,
   `google-cloud-run`, `stripe`, `httpx`; `[dev]` `pytest`, `ruff`, `mypy`, `pre-commit`, `python-hcl2`.
   Command lines use `argparse` (no CLI framework). Look up current versions (Context7 or PyPI), record
   them in FACTS.md, `uv lock`. Entry points: `reel = reel_studio.cli.reel:main`,
   `reelctl = reel_studio.cli.reelctl:main` (stubs that print usage).
2. **Contract-first layout** (D76 homes; no implementations beyond what a test needs):
   `reel_studio/settings.py` (pydantic-settings, reads `.env`; deployment fields have no default, any
   default carries `# default-because:`), `core/config.py` (loads `config/*.toml` into Pydantic models;
   unknown keys fail; every price row cites a FACTS id), `core/constants.py`, `core/ports.py` (every port in
   `docs/ARCHITECTURE.md` §3 as a `Protocol`), `core/errors.py` (typed exceptions per boundary and the
   user-message keys), `core/logging.py` (JSON lines, D74), `adapters/clock.py` (`SystemClock`, the only
   wall-clock reader) with `tests/fakes/clock.py` (`FrozenClock`). Empty packages `editor`, `api`, `cli`.
3. **Unit tests cannot spend money or read secrets.** `tests/conftest.py`: an autouse fixture makes any
   socket connection raise in unit tests (tests marked `emulator`, `e2e` or `paid` are exempt) and builds
   `Settings(_env_file=None, ...)` from explicit test values. `tests/unit/test_isolation.py` proves both.
   Markers in `pyproject.toml` with `--strict-markers`: `paid`, `slow`, `race`, `e2e`, `emulator`.
4. **Wire the guardrails; never edit them** (hooks block it): `make ci` runs
   `python3 .claude/hooks/selfcheck.py`, `uv run --quiet --no-project --python 3.13 python scripts/check_literals.py`
   and `python3 scripts/gates/_gate.py --self-test`. Ruff and mypy exclude `.claude/`,
   `scripts/check_literals.py` and `scripts/gates/`. Prove the scanner is live: plant `MAX_FILES = 40` and
   `"claude-sonnet-5-5"` in a scratch module under `reel_studio/`, run `make ci`, see R1 and R2, delete it.
5. **Makefile for GNU make 3.81** (the macOS default: no `.ONESHELL`, no `$(file ...)`, no `&:`):
   `setup` (uv sync --locked --all-extras, pre-commit install, copy `.env.example` to `.env` if missing),
   `test-fast` (< 60 s), `test`, `lint`, `types`, `ci`. `ci` = lint, types, test, the guardrail checks,
   then `ci-engine ci-web ci-cloud`, then writes `.ci-pass` with `git rev-parse HEAD` only when
   `git status --porcelain` is empty. `include mk/engine.mk mk/web.mk mk/cloud.mk`; each file defines its
   `ci-<lane>` target as a no-op that its lane fills later. `make ci` stays under 10 minutes; anything slower
   goes to `make prerelease` or to GitHub only.
6. **`scripts/ci-install.sh`**: uv 0.12.24, Node 24, Debian `ffmpeg`, gitleaks v8.30.1 (SHA-256
   `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`), then every
   `scripts/ci-install.d/*.sh` (create `engine.sh`, `web.sh`, `cloud.sh` as no-ops; lanes own them).
7. **pre-commit:** gitleaks as `language: system`, ruff. Prove gitleaks blocks a commit containing
   `sk-ant-api03-` + 93 letters or digits + `AA` (then remove it; never commit it).
8. **`.github/workflows/ci.yml`**, the only workflow (a hook blocks others until STEP-08's `deploy.yml`):
   on push and pull_request; `concurrency` per ref with `cancel-in-progress: true`; `timeout-minutes: 20`;
   `permissions: contents: read`; `runs-on: ubuntu-24.04`; actions pinned by full commit SHA (look them
   up); steps: checkout, `bash scripts/ci-install.sh`, `make ci`. No matrix, no cache steps, no artifacts.
9. **Protect `main`** with a ruleset through `gh api` (look the endpoint up on docs.github.com): pull
   request required, the CI check required, no force-push, no deletion. Paste the API answer.
10. **Repository files:** `LICENSE` (MIT, Kevin León 2026), `README.md` (what it is, quick start
    placeholder, link to docs), `SECURITY.md` (how to report a leaked key), `.gitattributes`
    (`docs/FACTS.md merge=union`, `docs/LESSONS.md merge=union`). Extend the kit's `.gitignore`; keep
    every line already in it.

## Done when (paste the evidence)

- `python3 scripts/gates/step01.py` prints `GATE step01 PASS` (run it in the background; it runs
  `make ci`). Paste the last 25 lines.
- The red run of task 4 and task 7, then green.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.

STOP and write "Needs Kevin" in HANDOFF.md if: a secret value appears in any output; a hook blocks
something this step needs; CI needs a paid runner.

Final message: five-line status board (done, partly, blocked, not started, next), then the PR link.
