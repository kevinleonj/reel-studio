# STEP-00 — Kevin's prerequisites on the Mac (about 20 minutes, once)

Outcome: every account, key and tool the next nine steps need exists, and a check prints OK for each.
Claude Code can run the checks; only Kevin can create accounts, keys and limits.

## 1. Accounts and keys (Kevin)

| # | What | Where | Goes into |
|---|---|---|---|
| 1 | The kit is already at `~/projects/reel/reel-studio`. Run `bash scripts/dev/first-run.sh` there: it checks the tools, commits the kit, creates the public GitHub repository `reel-studio`, pushes, then creates `.env` with the two folder paths filled in | Terminal on the Mac | git, GitHub, `.env` |
| 2 | Fill the keys in `.env` with an editor (`open -e .env`) | — | `.env` |
| 3 | Claude API key for the **reel-studio** workspace only | Claude Console → workspace reel-studio → API keys | `.env` `ANTHROPIC_API_KEY` |
| 4 | Workspace monthly spend limit **$100** (D59) | Claude Console → workspace reel-studio → limits | — |
| 5 | Gemini API key (optional for Tier 0: without it the voice toggle is off) | Google AI Studio | `.env` `GEMINI_API_KEY` |
| 6 | Stripe account, **test mode** secret key; then `stripe login` once | Stripe Dashboard | `.env` `STRIPE_SECRET_KEY` |
| 7 | (Before step 08) Cloudflare API token: Zone DNS Edit on limeralda.com only | Cloudflare → API tokens | `.env` `CLOUDFLARE_API_TOKEN` |
| 8 | (Before step 08) Resend account, full-access API key for setup | resend.com | `.env` `RESEND_API_KEY` |
| 9 | (Before step 08) Google Cloud billing account ID | `gcloud billing accounts list` | `.env` `GCP_BILLING_ACCOUNT` |
| 10 | (Before step 08) A second Claude key in workspace reel-studio, for the cloud | Claude Console | `.env` `CLOUD_ANTHROPIC_API_KEY` |
| 11 | (Before step 08) A Gemini key from a billing-enabled Google project, for friends' audio | Google AI Studio | `.env` `CLOUD_GEMINI_API_KEY` |

Context7: if you already use it at user level, decline the project's `.mcp.json` server when Claude Code asks.

Put the two keg-only tools first on your PATH, once:

```bash
echo 'export PATH="$(brew --prefix ffmpeg-full)/bin:$(brew --prefix node@24)/bin:$PATH"' >> "$HOME/.zshrc"
```

Open a new terminal before the checks.

Paths in `.env` must be absolute (`/Users/<you>/...`): `.env` is not a shell, so `$HOME` is not expanded.
Never paste a key into a chat or a commit. Never `export ANTHROPIC_API_KEY` in a terminal where you run
`claude`: Claude Code would bill that key instead of your Max plan (the app reads `.env` itself).

## 2. Tools on the Mac

| Tool | Install | Check (expected) |
|---|---|---|
| uv | `brew install uv` | `uv --version` → 0.12 or later (F39) |
| Python 3.13 | `uv python install 3.13` | `uv run --python 3.13 python -V` → 3.13.x |
| ffmpeg with zscale | `brew install ffmpeg-full` (plain `ffmpeg` lacks zimg). It is keg-only: see the PATH line below | `command -v ffmpeg` prints a path containing `ffmpeg-full`; `ffmpeg -hide_banner -filters` lists `zscale` and `tonemap` |
| Node.js 24 LTS | `brew install node@24` (keg-only: see the PATH line below) | `command -v node` prints a path containing `node@24`; `node -v` → v24.x (F41) |
| Docker | Docker Desktop (free for personal use and small companies) | `docker info` succeeds |
| Google Cloud CLI | already logged in | `gcloud auth list` shows Kevin's account |
| Terraform 1.16.5 | `brew install tfenv && tfenv install 1.16.5 && tfenv use 1.16.5` | `terraform version` → 1.16.5 (F36) |
| GitHub CLI | already logged in | `gh auth status` |
| Stripe CLI | `brew install stripe/stripe-cli/stripe` | `stripe version` |
| gitleaks | `brew install gitleaks` | `gitleaks version` → 8.30 or later (F44) |

## 3. Checks (Claude Code may run these; none prints a secret)

```bash
git -C "$HOME/projects/reel/reel-studio" rev-parse --show-toplevel
grep -o '^[A-Z_]*=' "$HOME/projects/reel/reel-studio/.env" | sort
command -v ffmpeg node
ffmpeg -hide_banner -filters | grep -E ' (zscale|tonemap) '
uv --version; node -v; terraform version | head -1; gh auth status 2>&1 | head -2; stripe version
```

Expected: the repository path; the names `ANTHROPIC_API_KEY=`, `GEMINI_API_KEY=`, `STRIPE_SECRET_KEY=`
(plus the step-08 names when you get there); two filter lines; the versions above.

Footage and old kit (first-run.sh writes both paths into `.env`):
`OLD_KIT_DIR=/Users/kevinleonj/projects/opus-build-day-make-reels` (the Agent SDK kit, for the A/B in step 04)
and `REEL_FIXTURES_DIR=/Users/kevinleonj/projects/reel-studio/input` (your old working copy; folders whose
names start with `_` are ignored). It holds cookies, creami and meat; step 04 needs 5, so add two more
folders of food clips before that step. Nothing in this project writes into either folder (D02).
