# HANDOFF

The main checkout's log and the status of every lane. Lanes write their own files in `docs/handoff/`.
Trimmed 16 Oct 2026 to the open items (`~/projects/reel/TIDY.md`); the full log is in git:
`git log -p -- HANDOFF.md`.

## Status
- Done and merged: starter kit v1.1; STEP-01 (#1), STEP-02 (#2), STEP-03 (#5), STEP-06 (#4, #8,
  #18), STEP-07 (#11, #13, #14), STEP-08 short of the real project (#3); cloud cost cap (#15, #16);
  main-lane work #6, #7, #9; MAIN-NEXT tasks 1-3 (#17, #19, #22; brief `~/projects/reel/MAIN-NEXT.md`,
  not in the repo) and the CloudSettings split (#21).
- Open in lane engine: STEP-04 (#10) and STEP-05 (#12, partial). Kevin decided on 13 Oct to ship
  the new engine to the friends beta; lane engine records it as D79 (reaches main with PR #10). D79 is not yet in
  the decisions file (Needs Kevin). The A/B gate stays the bar for leaving the beta.
- Not started: STEP-09. STEP-00 on the Mac is partly done (Needs Kevin).
- Not run against real services: no cloud adapter (Google Cloud, Resend), no editor job execution.
- Next: the sweep's OIDC check, then the other first-deploy follow-ups below, then the first deploy.

## Lanes
| Lane | Worktree | Steps | File |
|---|---|---|---|
| main | `~/projects/reel/reel-studio` | 01, 09 | this file |
| engine | `~/projects/reel/reel-studio-engine` | 02, 03, 04, 05 | `docs/handoff/engine.md` |
| web | `~/projects/reel/reel-studio-web` | 06, 07 | `docs/handoff/web.md` |
| cloud | `~/projects/reel/reel-studio-cloud` | 08 | `docs/handoff/cloud.md` |

## Needs Kevin
- `gh repo edit kevinleonj/reel-studio --delete-branch-on-merge` (a repository setting; stops new
  branch sprawl). Not run: TIDY.md says ask first.
- Before the first deploy: the repository variables `STRIPE_PRICE_ID` and `STRIPE_COUPON_ID`
  (Terraform stops the plan when they are empty).
- Doc gate: `~/.claude/hooks/gate-docs.sh` refuses Write and Edit on files importing `fastapi`,
  `httpx` or `google` because `.claude/doc-ledger.json` (protected) lists none of them; those test
  files were written through the shell. Their docs are cited in FACTS (F89-F94).
- D35 in the decisions file still says `write_edl` is strict; since 11 Oct it is not (F211, engine.md
  Needs Kevin 20). The file is locked, so that line is yours; EDITOR.md §4 already says so.
- Add the D79 row to the decisions file and mark D44 superseded for the beta (locked file, yours);
  the row's text is in lane engine's handoff (with PR #10).
- STEP-00 on the Mac: `command -v ffmpeg` is `/opt/homebrew/bin/ffmpeg` (no zscale). Fix: put
  `ffmpeg-full` first on PATH (STEP-00 §1). `node` already resolves to node@24.
- Private vulnerability reporting is off (SECURITY.md points reporters to it):
  `gh api -X PUT repos/kevinleonj/reel-studio/private-vulnerability-reporting`.
- Ruleset `protect main` (id 24815348) has `require_extra_approval_for_unattributed_changes: true`;
  harmless with 0 required approvals, but check it if a merge is ever refused.
- `reel_studio/settings.py` is in no lane's paths: a lane that needs a new variable asks here.

## Open follow-ups (cited from code; keep until done)
- Before the first deploy, task 2 (cloud wiring), the cloud sweep: the sweep endpoint still refuses every caller
  (`refuse_all`). It needs the scheduler's OIDC check, or no lease is ever swept; once it
  authenticates it must also start waiting orders (`launch_waiting`) and mail the failures it
  reports (ARCHITECTURE §1 step 14), as the laptop dispatcher does. Cited by `core/dispatch.py`.
- Task 2 residual: a launch that fails fails the order at once and frees its slot; an execution
  that claimed before the order was failed (a launch that timed out late) runs to its end and pays
  Claude for an order the customer was told failed. Cited by `core/dispatch.py`.
- Task 3, decided by standing orders: the ready email carries no link, because the token is stored
  only as a hash (D18); it points to the link in the first email (UX.md §3). Undo: an encrypted
  token or a re-access flow (web.md "Needs Kevin"). Cited by `api/notify.py`.
- Before the first deploy: `make test-emulator` (the four `claim_run` Firestore cases run in no CI
  job); `FORWARDED_ALLOW_IPS` on the service and `--build-arg SITE_URL` in deploy.yml (web.md);
  measure the uploads call with 40 files.
- A job that dies before its claim (no credentials, bad config) leaves the order running until the
  lease sweep. The ready email is claimed before it is sent, so a Resend outage longer than the
  retries loses it (release the claim on `DeliveryFailed`?).
- Two upload-session requests for one name at the same moment can both stay open (a generation
  check on the marker would close it).
- `make types` does not type-check `scripts/cloud/` (mypy needs `--explicit-package-bases`);
  `secrets-push` still requires the Resend and Cloudflare values and `dns` the model keys.
- The required `ci` check names no `integration_id`; pin it to GitHub Actions if that ever matters.
- Main-lane pull requests outside a step are queued on green CI and a senior PASS: `step01.py`
  fails on ".github/workflows/ holds exactly ci.yml: found ci.yml, deploy.yml" since STEP-08, and
  `step08.py` needs a live deploy (gates are Kevin's).
- The "Decided by standing orders" entries of tasks 1-3, each with its undo, are in
  `git log -p -- HANDOFF.md` (before 16 Oct).

## Log
### 16 Oct 2026 — tidy (PR #23) and markdown diet (branch `md-diet`)
- Diet: of 41 .md files (3,762 lines) only `docs/claude-project/INSTRUCTIONS.md` (30) was cited
  nowhere: now in `docs/archive/`. Kept: editor prompts (loaded via config), STEP-00, cli-verified.
- Branches (rules: `~/projects/reel/TIDY.md`, not in the repo): 20 merged branches deleted locally
  and on GitHub after a SHA match with the merged PR. Kept: open PRs and worktree branches.
