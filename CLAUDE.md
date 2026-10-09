# Reel Studio — rules for Claude Code

Reel Studio turns up to 40 food clips into an Instagram Reel (with text and clean) using our own loop
on the Claude Messages API and ffmpeg. Public repository, MIT. Three tiers share one code base: a
command line with your own key, a website on a laptop, a hosted beta on Google Cloud.

## Read before any work
1. `docs/DECISIONS.md` — locked. Do not re-open, re-ask or "improve" a decision. A hook blocks edits.
2. Your lane's handoff file — where the last session stopped. The SessionStart hook prints your lane:
   `docs/handoff/<lane>.md` in a lane worktree, `HANDOFF.md` in the main checkout.
3. The step you were given: `docs/build/STEP-NN.md`. Do only that step. Lanes and order: `docs/build/README.md`.
Specs, read the parts the step names: `docs/ARCHITECTURE.md`, `docs/EDITOR.md`, `docs/UX.md`,
`docs/INFRA.md`. Facts with sources: `docs/FACTS.md`. Past mistakes: `docs/LESSONS.md`.

## Commands (the step that adds each one is in brackets; before that step it does not exist)
- `make setup` · `make test-fast` (unit, < 60 s) · `make test` · `make ci` (writes `.ci-pass` on a clean tree) [01]
- `uv run reel render --edl <file> <folder>` [02] · `uv run reel make <folder> --style <style>` [03]
- `make eval FIX=<name> [MODEL=haiku]` [03] · `make ab` and `make ab-pick` [04]
- `make up` / `make down` [06] · `make prerelease` (Playwright + Lighthouse) [06] · `make stripe-listen` [07]
- `uv run reelctl ...` [07] · `make smoke URL=<url>`, `make secrets-push`, `make dns`, `make stripe-setup` [08]
- Paid API calls happen only in `reel make` and `make eval`/`make ab`, never in tests. Stay inside the step's budget.
- The app reads `.env` itself (pydantic-settings); never pass `--env-file` on the command line.
- `python3 scripts/gates/stepNN.py [--local]` [every step]: the only definition of done (D78). It runs
  `make ci`, so start it with the Bash tool's background option and read its output when it ends.

## How you work on every task
1. Plan mode: list the files you will change, the facts you must look up, the failing test you will write.
2. Look things up, never guess: any SDK call, CLI flag, Terraform argument, price, limit or region
   comes from Context7 or the vendor's page. Add or update the row in `docs/FACTS.md` (URL + date)
   in the same commit. If you cannot confirm it, write UNCONFIRMED and do not ship code that depends on it.
3. Write the failing test, run it, see it fail for the right reason.
4. Implement the smallest change that passes. `make test-fast` after each change.
5. `make ci` before every push (the push hook checks `.ci-pass` equals HEAD).
6. One commit per logical unit, `git add <explicit paths>`. Update your handoff file (before/after, follow-ups).
7. Finish: `git fetch origin && git merge origin/main`, `make ci`, push, `gh pr create`, wait for CI, then
   run the gate without `--local` until it prints `GATE stepNN PASS`. Kevin merges; you never do.
8. If a mistake happened, add a line to `docs/LESSONS.md` with the test that now blocks it.

## Code rules
- Ports and adapters: code touches the outside only through `reel_studio/core/ports.py`. Every port has
  a fake used in tests.
- Every value has a home (D76): tunables in `config/*.toml`; deployment values in `reel_studio/settings.py`
  (no default unless `# default-because:`); format constants in `reel_studio/core/constants.py` with a
  source comment; text in `web/src/copy/en.json`; colours and sizes in `web/src/styles/tokens.css`.
  `scripts/check_literals.py` runs after every edit and in `make ci`. Never weaken it; if a literal must
  stay, write the case under "Needs Kevin" (only Kevin adds allowlist entries).
- Lanes: edit only your lane's paths (`.claude/lanes.json`; the hooks enforce it). Only the web lane
  starts containers.
- The Mac: GNU make 3.81, bash 3.2 and BSD tools. Write scripts in Python, not shell; no `sed -i`,
  `readlink -f`, `timeout`, `sha256sum`, `.ONESHELL`. Images are `linux/amd64` and build slowly under
  emulation on Apple silicon: build them only when the step needs it; CI builds them anyway.
- Logs are JSON lines with `order_id`, `stage`, `event`, `latency_ms`, `outcome`. Every external call is
  logged once. Never log a key, a token, an email body or a query string.
- Errors: typed exceptions per boundary (see `docs/EDITOR.md` §10); no bare `except`; never swallow an
  error without logging it; user-facing messages come from one table.
- Python: `x if x is not None else default`, never `x or default` for values that may be `0` or `""`.
- Modules under about 300 lines; functions do one thing; comments say why, not what.
- No new dependency without one line in `HANDOFF.md` saying why and which alternative lost.
- Tests: freeze the clock; no network in unit tests; paid tests are marked `paid` and run only via
  `make eval`; golden files change only with `REEL_ALLOW_GOLDEN=1` and a reason in the commit.

## Never
- Post to Instagram, add music, or modify a user's input files.
- Read or print `.env`, secrets or environment values (names only: `grep -o '^[A-Z_]*=' .env`).
- Add `claude-agent-sdk` or the tool runner to the product, or give the product's model a shell or
  file tool (D30, D31).
- Run `terraform apply` or `destroy`, force-push, push without a green `make ci`, or merge with red CI.
- Grant IAM roles outside `docs/ARCHITECTURE.md` §5, or create an always-on cost not in `docs/INFRA.md` §5.
- Spend more API money than the step's budget.
- Edit the gates, the scanner, its allowlist, the hooks or `.claude/lanes.json` (protected), merge a pull
  request, add a workflow file, or `export` a key in a shell.

## Stop and write "Needs Kevin" in your handoff file when
A decision blocks the work; a secret value appears in any output; a paid or irreversible action is
next that the step did not list; the same tool or test fails twice for a reason you cannot fix.

## Definition of done (every step)
- Failing test existed, now passes; full suite green; CI Mirror Gate green.
- Runtime evidence pasted.
- Diff touches only the stated scope; no new dependency without a reason.
- No secret, no hard-coded client value; docs cited for every external API used.
- `HANDOFF.md` updated with before/after and follow-ups. (In a lane: `docs/handoff/<lane>.md`.)

## Mistakes this repository blocks, and how
| Mistake | Guard |
|---|---|
| Declaring done without proof | Gate script per step; `/goal` waits for its PASS line |
| Hard-coded numbers, URLs, model names, text, colours | `check_literals.py` after every edit and in `make ci` |
| Defaults nobody chose | Settings without defaults; Terraform explicit-arguments policy (STEP-08) |
| Over-built CI | One `ci.yml` calling `make ci`; hook blocks any other workflow file |
| Tests that pass by editing tests | Golden files, gates and the scanner are hook-protected |
| Unit tests that call the network or read `.env` | `tests/conftest.py` isolation, proven by `test_isolation.py` |
| Secrets in output or commits | Hooks block env dumps and `.env` reads; gitleaks pre-commit; `--no-verify` blocked |
| Lanes overwriting each other | `.claude/lanes.json` enforced on edit and at Stop |

## Final message of a session
Five lines first: done · partly · blocked · not started · next. Then the evidence and the PR link.
