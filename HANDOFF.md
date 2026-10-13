# HANDOFF

The main checkout's log and the status of every lane. Lanes write their own files in `docs/handoff/`.
Newest entry on top.

## Status board
MAIN-NEXT in progress (13 Oct 2026): task 1, the parked docs and config (branch `main-parked`)
- Done: starter kit v1.1; STEP-01 (#1), STEP-02 (#2), STEP-03 (#5), STEP-08 short of the real project
  (#3), STEP-06 except task 8 (#4, #8), STEP-07 (#11, #13, #14), `httpx2` and laptop `WebSettings`
  (#6), auto-merge guardrail (#7), Stripe ids (#9), cloud cost cap (#15, #16), all merged
- Partly: STEP-00 on the Mac (see Needs Kevin); STEP-04 (#10 open) and STEP-05 (#12 open, partial)
  in lane engine; MAIN-NEXT tasks 1-3
- Blocked: —
- Not started: STEP-09
- Next: MAIN-NEXT task 2 (cloud composition) after task 1's pull request

## Lanes
| Lane | Worktree | Steps | File |
|---|---|---|---|
| main | `~/projects/reel/reel-studio` | 01, 09 | this file |
| engine | `~/projects/reel/reel-studio-engine` | 02, 03, 04, 05 | `docs/handoff/engine.md` |
| web | `~/projects/reel/reel-studio-web` | 06, 07 | `docs/handoff/web.md` |
| cloud | `~/projects/reel/reel-studio-cloud` | 08 | `docs/handoff/cloud.md` |

## Needs Kevin
- D35 in the decisions file still says `write_edl` is strict; since 11 Oct it is not (F211, engine.md
  Needs Kevin 20). The file is locked (a hook blocks edits), so that line is yours; EDITOR.md §4 now
  says so.
- Merge PR #1 (STEP-01). The three lanes wait for it.
- Two more footage folders in `REEL_FIXTURES_DIR` before STEP-04 (5 needed, 3 present).
- STEP-00 leftovers on the Mac, needed from STEP-02 (ffmpeg) and STEP-06 (node): `command -v ffmpeg` is
  `/opt/homebrew/bin/ffmpeg` (plain, no zscale), and `node` is Homebrew Node 26, which fails to start
  (`libsimdjson.33.dylib` missing). Fix: the PATH line in STEP-00 §1 for `ffmpeg-full` and `node@24`.
- Turn on private vulnerability reporting (SECURITY.md points reporters to it; it is off; until then
  SECURITY.md asks for an empty "Security contact request" issue):
  `gh api -X PUT repos/kevinleonj/reel-studio/private-vulnerability-reporting`.
- Ruleset `protect main` (id 24815348): GitHub added `require_extra_approval_for_unattributed_changes: true`
  by default; harmless with 0 required approvals, but check it if a merge is ever refused.
- `.env` names were not checked in STEP-01 discovery (the names-only grep was denied); STEP-01 needs no key.
- `reel_studio/settings.py` is not in any lane's paths, so STEP-01 declared every `.env.example` variable
  (one class per consumer; a test keeps the two in step). A lane that needs a new variable asks here.

## Log
### 13 Oct 2026 — MAIN-NEXT task 1: the parked docs and config (branch `main-parked`)
- Before: the lanes' "For MAIN" doc edits waited (INFRA §1, §2, §5 from cloud.md; ARCHITECTURE §3, §4,
  §5 and INFRA §4 behind the code; EDITOR §2 and §4 behind the brief and `write_edl`); `.gitignore`
  matched `.claude/state/` only at the root (L305) and missed `*.tfvars`, `tfplan.json`, `crash.log`;
  `provider_rejected` and `cloud_unavailable` had no message, so the order page showed the generic
  cutting failure; `gcp_storage.py` carried a local `type: ignore[import-untyped]`.
- After: INFRA §1 first-deploy order with `make spend-cap` and `make github-env`; §2 the sampled request
  log exclusion (F415) and the registry's scanning off (F416); §4 two approvals (plan and apply both in
  `beta`, F411) and how smoke reads; §5 the Cloud Run spend cap (F414). ARCHITECTURE §3 the launcher is
  at most once and reads `queue.run_token`; §4 the worker claims the token by setting
  `queue.claimed_at` in a transaction (`take_slot` already writes `started_at`); §5 the
  conditional projectIamAdmin (F410), the `beta`
  environment, `serviceAccountUser` granted by the main root. EDITOR §2 brightness, length ranges and
  reading time; §4 `write_edl` not strict; §10 rows for `ProviderRejected` and `CloudUnavailable`.
  `en.json`, `types.ts` and `StatusViews.tsx` carry both codes (Start again). mypy override for
  `google.cloud.storage.*` (F88: 3.17.0 has no `py.typed`; mypy fails without the override).
  `.dockerignore` already existed (#9).
- Tests first: `tests/contract/test_web_copy.py` (both codes in `FAILED_CODES`) and
  `tests/unit/test_gitignore.py` (`git check-ignore --no-index` on nested state and Terraform files)
  failed, then passed.
- Decided by standing orders: `roles/iam.serviceAccountUser` stays in `infra/main/iam.tf`, where the
  accounts are created, and ARCHITECTURE §5 now says so (cloud.md "your call"). Why: nothing is applied
  yet, and moving the accounts to bootstrap would put every account change behind Kevin's manual apply.
  Undo: move the three accounts and the grant into `infra/bootstrap/` and revert the §5 row.
- Not done here: cloud.md's hook items (`chore(auto)`, `gate-hardcode.sh`) are Kevin's global hooks;
  the review-verdict path in `.claude/lanes.json` is protected.

### 11 Oct 2026 — step07-settings (PR #9): Stripe ids and .dockerignore
- Before: `WebSettings` had no Stripe price or coupon id (web.md "For MAIN (STEP-07)"); no
  `.dockerignore`, so every build context carried the dotenv file (web.md "For MAIN").
- After: `stripe_price_id`, `stripe_coupon_id` (optional with `PAYMENTS=off`; with `PAYMENTS=stripe` all
  four Stripe values required, the error names the missing ones), passed by `compose.yaml`, lines in
  `.env.example`; `.dockerignore` with `tests/unit/test_dockerignore.py` (secrets out, every COPY source
  in); the `DATA_DIR` comment fixed. `make ci` green: 768 passed. PR #9 queued for auto-merge.
- Not done: the `stripe` doc-ledger entry for the web worktree (protected, another worktree: Kevin).
- Lesson L21: `origin/main` moved mid-session because worktrees share refs; squash onto the merge base.

### 11 Oct 2026 — guard-auto-merge: sessions may queue their own pull requests (Kevin approved)
- Before: `guard_bash.py` blocked every `gh pr merge`; Kevin merged every pull request by hand.
- After: exactly `gh pr merge <N> --auto --squash` is allowed (any other flag, a branch name instead of a
  number, `-R`, `--admin`, `gh api …/merge` and GraphQL merges stay blocked); `selfcheck.py` has 9 new
  block cases and 2 allow cases (476 checks). Repository setting `allow_auto_merge` is on. Ruleset
  `protect main` (id 24815348, active) already requires the `ci` check, the only CI check:
  `{"checks":[{"context":"ci"}],"type":"required_status_checks"}`, so auto-merge waits for green CI.
  CLAUDE.md, the hooks README and docs/build/README.md say so.
- Also: `[tool.ruff] force-exclude = true`. Kevin's format-on-save hook runs `ruff format <file>`, and
  without it ruff reformatted the protected `guard_bash.py` (235 insertions) despite `extend-exclude`;
  that commit was dropped before anything was pushed.
- Follow-up: the required check names no `integration_id`, so any status named `ci` satisfies it; only
  repository writers can post statuses. Pin it to GitHub Actions if that ever matters.

### 11 Oct 2026 — main-settings: httpx2 and the laptop WebSettings
- Before: `httpx2` only transitive (via `anthropic`) although the engine's Claude adapter imports it
  (engine.md Needs Kevin 21); `WebSettings` lacked the laptop runtime values (web.md Needs Kevin).
- After: `httpx2>=2.13.1` in `[editor]` (F87; no new package, already locked); a test fails on any
  third-party import under `reel_studio/` that pyproject does not declare. `WebSettings` gains
  `firestore_project`, `smtp_host`, `smtp_port`, `data_dir`, `web_dist`, `voice_available`, all required,
  with `.env.example` lines for the laptop (compose service names, `VOICE_AVAILABLE=false`).
- Follow-ups: lane web wires these into `api/deps.py` and the compose file (task 6);
  `dispatcher_poll_seconds` stays a `config/limits.toml` tunable, as the web lane proposed.

### 9 Oct 2026 — STEP-01 skeleton, guardrails, CI
- Before: docs, hooks, scanner and gates only; no package, no Makefile, no CI, `main` unprotected.
- After: `reel_studio` package (D70) with every dependency locked (F80); `settings.py` (EditorSettings,
  BuildSettings, WebSettings, CloudSettings, no default without a reason); `core/config.py` (strict models,
  Decimal money, price facts checked against FACTS.md); `core/ports.py` (8 ports, binding names);
  `core/errors.py` (boundaries and user-message keys); `core/logging.py` (D74 JSON lines); `SystemClock`
  and `FrozenClock`; `tests/conftest.py` blocks sockets and `.env`. Makefile for make 3.81 with
  `mk/<lane>.mk`; `scripts/ci-install.sh` (uv, Node, gitleaks pinned by SHA-256; Debian ffmpeg);
  pre-commit (gitleaks, ruff); `ci.yml` (full-history checkout for gitleaks); LICENSE, README, SECURITY,
  .gitattributes.
- Senior review (CHANGES-REQUIRED on 0800ab4) fixed: `make ci` now syncs every extra first (CI would have
  had no ruff); blank `KEY=` lines count as missing (`env_ignore_empty`, F81); config rejects a model id
  with no price; tests also block UDP, name lookups and gRPC channels and scrub Google credential variables;
  logs carry `severity` and RFC 3339 UTC `time` (F86); README lists gitleaks.
- Proven red then green: scanner reports R1 `40` and R2 `claude-sonnet-5-5` from a planted module;
  pre-commit refuses a commit holding an Anthropic-shaped key (built at runtime in a throwaway repo).
- Choices: error keys other than `cost_cap` are named by us (EDITOR.md §10 names none); `make ci` also runs
  `gitleaks git` (ARCHITECTURE.md "gitleaks in pre-commit and CI"); pre-commit hooks are local so ruff has
  one version (uv.lock); `ci.yml` has no paths-ignore because the ruleset requires its check on every PR.
- Dependencies for lane engine, declared here because lanes cannot edit pyproject.toml: `scenedetect-headless`,
  `opencv-python-headless`, `numpy`, `pillow-heif` in `[editor]` (F84). `scenedetect` lost: it pulls the GUI
  `opencv-python`, which needs libGL on the slim image (D72) and clobbers the headless `cv2`. mypy override for
  `scenedetect` only (F85).
- TONIGHT.md main item 1: `EditorSettings.ffmpeg_path` and `ffprobe_path` are required absolute paths
  (`FFMPEG_PATH`, `FFPROBE_PATH` in `.env.example`); `.claude/settings.local.json` is gitignored.
- Second senior review: PASS on 9e97c20 (diff sha256 e419941d…). Its warnings and cheap suggestions are
  also fixed: the no-default and dotenv-isolation tests now fail for their stated reason; the price check is
  pinned for all four model ids; `sendmsg` and the marker rule are tested; more SDK variables are scrubbed;
  socket tests time out fast; the log time test uses a frozen instant; every make target runs with all
  extras; `grpcio` is declared in `[dev]` because the test network block imports it (it lost to "rely on
  the transitive copy from `[api]`", which breaks the day `[api]` drops it).
- GitHub: PR #1 opened (not a draft); `ci` green on push and pull_request; ruleset `protect main` created
  through `POST /repos/{owner}/{repo}/rulesets` (F79): pull request required, check `ci` required,
  no force-push, no deletion, no bypass actors.
- Follow-ups: lanes fill `ci-<lane>` and `scripts/ci-install.d/<lane>.sh`; port payload types settle with
  their first adapter (STEP-03, STEP-06); `.claude/doc-ledger.json` is kept for Kevin's user-level doc gate;
  lane cloud must set `FFMPEG_PATH=/usr/bin/ffmpeg` and `FFPROBE_PATH=/usr/bin/ffprobe` for the render job
  and image (D72), since `EditorSettings` now requires them.

### 9 Oct 2026 — starter kit v1.1
- Before: kit v1 (Vite front end, a narrow literal test, hooks for one session).
- After: Astro (D71), analytics seam off (D75), hard-coded-value scanner (D76), Mac with three lanes (D77),
  a gate script per step (D78). Hooks: 465 self-checks under Python 3.9 and 3.13; scanner self-test 34/34;
  gates self-test 30/30.
- Follow-ups: STEP-00, STEP-01.
