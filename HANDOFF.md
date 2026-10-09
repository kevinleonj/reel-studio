# HANDOFF

The main checkout's log and the status of every lane. Lanes write their own files in `docs/handoff/`.
Newest entry on top.

## Status board
- Done: starter kit v1.1; STEP-01 skeleton, guardrails, CI (PR `step-01-skeleton`, Kevin merges)
- Partly: STEP-00 on the Mac (ffmpeg-full and node@24 not on PATH, see Needs Kevin)
- Blocked: —
- Not started: STEP-02 to STEP-09
- Next: merge STEP-01, then the three lanes (`scripts/dev/lane.sh`): engine STEP-02, web STEP-06, cloud STEP-08

## Lanes
| Lane | Worktree | Steps | File |
|---|---|---|---|
| main | `~/projects/reel/reel-studio` | 01, 09 | this file |
| engine | `~/projects/reel/reel-studio-engine` | 02, 03, 04, 05 | `docs/handoff/engine.md` |
| web | `~/projects/reel/reel-studio-web` | 06, 07 | `docs/handoff/web.md` |
| cloud | `~/projects/reel/reel-studio-cloud` | 08 | `docs/handoff/cloud.md` |

## Needs Kevin
- Two more footage folders in `REEL_FIXTURES_DIR` before STEP-04 (5 needed, 3 present).
- STEP-00 leftovers on the Mac, needed from STEP-02 (ffmpeg) and STEP-06 (node): `command -v ffmpeg` is
  `/opt/homebrew/bin/ffmpeg` (plain, no zscale), and `node` is Homebrew Node 26, which fails to start
  (`libsimdjson.33.dylib` missing). Fix: the PATH line in STEP-00 §1 for `ffmpeg-full` and `node@24`.
- `.env` names were not checked in STEP-01 discovery (the names-only grep was denied); STEP-01 needs no key.
- `reel_studio/settings.py` is not in any lane's paths, so STEP-01 declared every `.env.example` variable
  (one class per consumer; a test keeps the two in step). A lane that needs a new variable asks here.

## Log
### 9 Oct 2026 — STEP-01 skeleton, guardrails, CI
- Before: docs, hooks, scanner and gates only; no package, no Makefile, no CI, `main` unprotected.
- After: `reel_studio` package (D70) with every dependency locked (F80); `settings.py` (EditorSettings,
  BuildSettings, WebSettings, CloudSettings, no default without a reason); `core/config.py` (strict models,
  Decimal money, price facts checked against FACTS.md); `core/ports.py` (8 ports, binding names);
  `core/errors.py` (boundaries and user-message keys); `core/logging.py` (D74 JSON lines); `SystemClock`
  and `FrozenClock`; `tests/conftest.py` blocks sockets and `.env`. Makefile for make 3.81 with
  `mk/<lane>.mk`; `scripts/ci-install.sh` (uv, Node, gitleaks pinned by SHA-256; Debian ffmpeg);
  pre-commit (gitleaks, ruff); `ci.yml`; ruleset on `main`; LICENSE, README, SECURITY, .gitattributes.
- Proven red then green: scanner reports R1 `40` and R2 `claude-sonnet-5-5` from a planted module;
  pre-commit refuses a commit holding an Anthropic-shaped key (built at runtime in a throwaway repo).
- Choices: error keys other than `cost_cap` are named by us (EDITOR.md §10 names none); `make ci` also runs
  `gitleaks git` (ARCHITECTURE.md "gitleaks in pre-commit and CI"); pre-commit hooks are local so ruff has
  one version (uv.lock); `ci.yml` has no paths-ignore because the ruleset requires its check on every PR.
- Follow-ups: lanes fill `ci-<lane>` and `scripts/ci-install.d/<lane>.sh`; port payload types settle with
  their first adapter (STEP-03, STEP-06); `.claude/doc-ledger.json` is kept for Kevin's user-level doc gate.

### 9 Oct 2026 — starter kit v1.1
- Before: kit v1 (Vite front end, a narrow literal test, hooks for one session).
- After: Astro (D71), analytics seam off (D75), hard-coded-value scanner (D76), Mac with three lanes (D77),
  a gate script per step (D78). Hooks: 465 self-checks under Python 3.9 and 3.13; scanner self-test 34/34;
  gates self-test 30/30.
- Follow-ups: STEP-00, STEP-01.
