# Guard hooks

Wired in `.claude/settings.json`. Python 3.9+ standard library only, because on a Mac the `python3` on
PATH can be the Xcode Command Line Tools' 3.9. Shared helpers are in `_common.py`. The hooks run git and
nothing else, except the project's own tools where noted (`uv`/ruff, the literal scanner, `make test-fast`).
Verify on both ends of the supported range (465 checks; STEP-01 ports them into pytest):

    uv run --no-project --python 3.9 python .claude/hooks/selfcheck.py
    uv run --no-project --python 3.13 python .claude/hooks/selfcheck.py

These hooks are a seatbelt, not a security boundary: a determined process can always find a
command the patterns miss. The real limits on damage are elsewhere: a workspace-scoped Claude key with
a $100 monthly limit, keys that can be rotated, branch protection on `main`, and Terraform applied only
by the reviewed deploy workflow.

A crashed hook does not block in Claude Code, so the two guards are wrapped in `settings.json`: if
`guard_bash.py` or `guard_paths.py` cannot run (no `python3`, a too-old one, a crash), the call is
blocked with that reason instead of slipping through.

## Mac specifics

- Paths are compared in lowercase: the default macOS file system treats `Docs/DECISIONS.md` as
  `docs/DECISIONS.md` and runs `GIT` as `git`.
- Temp folders are compared by real path: `/tmp` is a link to `/private/tmp`, and `$TMPDIR` lives under
  `/var/folders`, which is `/private/var/folders`.
- Finder's `.DS_Store` files never count as a lane's change. Add `.DS_Store` to `.gitignore` anyway.

## Worktrees and lanes

Up to four sessions run at once, each in its own git worktree (`reel-studio`, `reel-studio-engine`,
`-web`, `-cloud`). Every hook takes the repository root from `git rev-parse --show-toplevel` in the
session's current folder (fallback: `CLAUDE_PROJECT_DIR`, then that folder), so each worktree has its own
root, its own `.ci-pass` and its own lane.

A worktree's lane is the one word in its untracked `.lane` file: `engine`, `web` or `cloud`. No `.lane` file
means lane `main`, which may edit every path. Any other lane may edit only its own path prefixes in
`.claude/lanes.json` plus the `shared` ones (keys starting with `_` are comments). A word that is not a lane
there (even `main`) blocks every edit. A blocked edit names the lane that owns the path and points to
"Needs Kevin" in `docs/handoff/<lane>.md`. Sessions cannot change `.lane` or `lanes.json`. Untracked files
count as changes for the Stop check, so generated folders (`__pycache__/`, `node_modules/`) belong in
`.gitignore`.

| Hook | Event | Blocks (exit 2, or a Stop "block") | Allows |
|---|---|---|---|
| `session_check.py` | SessionStart (startup, resume, clear, compact) | Never blocks. Prints a warning when the system is neither macOS nor Linux, when the Python running the hooks is older than 3.9, or when `ANTHROPIC_API_KEY` is exported (checks the name only, never prints the value), then the lane and its paths | — |
| `guard_bash.py` | PreToolUse, Bash and PowerShell | Every PowerShell call ("Use the Bash tool in this repository."). Reading `.env` in any letter case (also quoted, escaped or globbed; recursive `grep`) (except names-only `grep -o '^…='` and values of `OLD_KIT_DIR`, `REEL_FIXTURES_DIR`, `GCP_PROJECT`, `GCP_REGION`, `SITE_URL`, `PAYMENTS`); `terraform apply/destroy`; `terraform state/import/taint/untaint`; force-push; push to `main`; push when this worktree's `.ci-pass` ≠ HEAD; `git commit --no-verify`/`-n` (also inside `-nm`), `git push --no-verify`, `SKIP=…gitleaks…` with a commit or push, `git -c core.hooksPath=…` with a commit or push, `git config core.hooksPath <value>`; `gh pr merge` and `gh api …/merge`, `…/merges` or a GraphQL merge; `gcloud run deploy`, `run jobs deploy`, `run services update`, `run jobs update`, `run services replace`, `run jobs replace`, `run services update-traffic`, `builds submit`; any `stripe` command with `--live`; `git worktree remove/prune`; `git clean -x`/`-X` (unless `-n`); any command naming `.ci-pass`; push refspecs naming `main`; `docker inspect`, `docker compose config`, `docker exec … env`; shell writes (`>`, `sed -i`, `cp`, `mv`, `python`, … in any case) to `.claude/`, `.lane`, `docs/DECISIONS.md`, `tests/golden/`, `scripts/gates/`, `scripts/check_literals.py` or `tests/literal_allowlist.toml` without the override, or to `.git/hooks/` and `.git/config` at all; new files in `.github/workflows/`; `printenv`, bare `env`, echoing `*KEY*`/`*TOKEN*`/`*SECRET*`; `gcloud secrets versions access`; `gcloud … delete`; bucket `rm`; `curl … \| sh`; `pip install`; global npm installs; `claude-agent-sdk`; live Stripe or Claude keys in a command; recursive `rm` outside the repository or a temp folder. The word-by-word rules read the command the way bash does, so `g"i"t commit -n` is caught and `git commit -m "fix -n handling"` is not | Running `scripts/check_literals.py` or `scripts/gates/*.py`; everything else |
| `guard_paths.py` | PreToolUse, Edit/Write/MultiEdit/NotebookEdit | All in any letter case: `.env*` except `.env.example`; Terraform state, plans, `.terraform/`; `uv.lock`, `package-lock.json`; `docs/DECISIONS.md` unless `REEL_ALLOW_DECISION_EDIT=1`; `tests/golden/**` unless `REEL_ALLOW_GOLDEN=1`; `scripts/gates/**` unless `REEL_ALLOW_GATE_EDIT=1`; `scripts/check_literals.py` and `tests/literal_allowlist.toml` unless `REEL_ALLOW_LITERAL_EDIT=1`; `.git/hooks/**` and `.git/config` (no override); any `.github/workflows/` file except `ci.yml` and `deploy.yml` (no override); `.claude/hooks/**`, `.claude/agents/**`, `.claude/settings*.json`, `.claude/lanes.json` and `.lane` unless `REEL_ALLOW_HOOK_EDIT=1`; `.ci-pass`; any content containing `disableAllHooks`; any path outside the worktree except a temp folder; any path outside the worktree's lane | Everything else |
| `post_edit.py` | PostToolUse, Edit/Write/MultiEdit | Formats and lints edited `.py` files with ruff and reports leftovers to Claude. Once `scripts/check_literals.py` exists, runs it on `reel_studio/**/*.py` and `web/src/**/*.{ts,tsx,astro,css}` with `uv run --quiet --no-project --python 3.13 python` (it needs 3.11+), or `python3` without uv; its findings go back to Claude (exit 2) with where the value belongs. A scanner that fails or takes over 30 s never blocks: Claude gets the warning as context | — |
| `stop_gate.py` | Stop | In a lane: changed files outside the lane's and shared paths (commits since the merge base with `origin/main`, else `main`, plus uncommitted and untracked files). Everywhere: a red `make test-fast` after code changes that `make ci` has not stamped. Reminds about `docs/handoff/<lane>.md` (`HANDOFF.md` on main). Respects `stop_hook_active` | Turns with no code change, or before the Makefile exists |

The override variables (`REEL_ALLOW_HOOK_EDIT`, `REEL_ALLOW_DECISION_EDIT`, `REEL_ALLOW_GOLDEN`,
`REEL_ALLOW_GATE_EDIT`, `REEL_ALLOW_LITERAL_EDIT`) are set by Kevin when he starts a session on purpose,
for example `REEL_ALLOW_DECISION_EDIT=1 claude`. Claude Code cannot set them for its own process.
