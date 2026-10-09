#!/bin/bash
# Reel Studio, STEP-00 on the Mac. Kevin runs this once from the kit folder:
#   bash ~/projects/reel/reel-studio/scripts/dev/first-run.sh
# Safe to run again. Order: check tools -> self-tests -> first commit -> GitHub repo -> .env.
# Written for macOS /bin/bash 3.2.
set -eu
set -o pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$ROOT"
[ -f .claude/lanes.json ] || { echo "Run this from the Reel Studio kit folder." >&2; exit 1; }

say() { printf '\n== %s\n' "$*"; }
need_fail=0
need() { # now-required tool: name, check command, fix, [command that shows what was found]
  if eval "$2" >/dev/null 2>&1; then printf '  OK     %s\n' "$1"
  else
    printf '  FAIL   %s  -> %s\n' "$1" "$3"
    if [ -n "${4:-}" ]; then printf '         found: %s\n' "$(eval "$4" 2>&1 | tr '\n' ' ')"; fi
    need_fail=$((need_fail + 1))
  fi
}
later() { # needed by a later step: name, check command, step, fix
  if eval "$2" >/dev/null 2>&1; then printf '  OK     %s\n' "$1"
  else printf '  LATER  %s (needed in %s)  -> %s\n' "$1" "$3" "$4"; fi
}

say "Tools needed now (STEP-01)"
need "macOS"                          '[ "$(uname -s)" = Darwin ]' "run this on the Mac"
need "python3 3.9+ (the hooks)"       'python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"' "xcode-select --install"
need "git"                            'git --version' "xcode-select --install"
need "git user.name and user.email"   'git config user.name && git config user.email' 'git config --global user.name "Kevin León"; git config --global user.email <your GitHub email>'
need "gh logged in"                   'gh auth status' "gh auth login"
need "uv 0.12+"                       'uv --version | awk "{split(\$2, v, \".\"); exit !(v[1] > 0 || v[2] >= 12)}"' "uv self update (updates the uv your terminal runs); if it refuses, move ~/.local/bin/uv and ~/.local/bin/uvx aside so Homebrew's uv answers" 'command -v uv; uv --version'
need "gitleaks"                       'gitleaks version' "brew install gitleaks"
need "Claude Code"                    'claude --version' "already installed on this Mac?"
need "ANTHROPIC_API_KEY not exported" '[ -z "${ANTHROPIC_API_KEY+x}" ]' "remove the export from ~/.zshrc and open a new terminal (Claude Code would bill that key)"

say "Tools needed in later steps"
later "ffmpeg with zscale and tonemap" '[ "$(ffmpeg -hide_banner -filters 2>/dev/null | grep -c -E " (zscale|tonemap) ")" = 2 ]' "STEP-02" "brew install ffmpeg-full + PATH line"
later "Node 24"                        'node -v | grep -q "^v24\."' "STEP-06 (CI installs its own)" "brew unlink openssl@3; brew install node@24; put /opt/homebrew/opt/node@24/bin first on PATH"
later "Docker running"                 'docker info' "STEP-02 image, STEP-06" "start Docker Desktop"
later "Stripe CLI"                     'stripe version' "STEP-07" "brew install stripe/stripe-cli/stripe; stripe login"
later "Terraform 1.16.5"               'terraform version | head -1 | grep -q "v1\.16\.5"' "STEP-08" "brew install tfenv && tfenv install 1.16.5 && tfenv use 1.16.5"
later "gcloud logged in"               'gcloud auth list --format="value(account)" | grep -q @' "STEP-08" "gcloud auth login"

if [ "$need_fail" -gt 0 ]; then
  printf '\n%s required check(s) failed. Fix them, open a new terminal, run this again.\n' "$need_fail"
  exit 1
fi

say "Self-tests of the guardrails (about a minute)"
uv python install 3.13 >/dev/null
python3 .claude/hooks/selfcheck.py | tail -1
uv run --quiet --no-project --python 3.13 python scripts/check_literals.py --self-test | tail -1
python3 scripts/gates/_gate.py --self-test | tail -1

say "Git: first commit"
if [ ! -d .git ]; then
  git init --quiet -b main
fi
touch .env.probe-ignored
git check-ignore -q .env.probe-ignored || { rm -f .env.probe-ignored; echo "STOP: .gitignore does not ignore .env files" >&2; exit 1; }
rm -f .env.probe-ignored
if ! git rev-parse --verify --quiet HEAD >/dev/null; then
  git add -A
  git commit --quiet -m "Starter kit v1.1"
  echo "  committed: $(git log --oneline -1)"
else
  echo "  already committed: $(git log --oneline -1)"
fi

say "GitHub"
OWNER="$(gh api user --jq .login)"
if git remote get-url origin >/dev/null 2>&1; then
  echo "  origin: $(git remote get-url origin)"
elif gh repo view "$OWNER/reel-studio" >/dev/null 2>&1; then
  echo "STOP: github.com/$OWNER/reel-studio already exists. Check it, then: git remote add origin <url> && git push -u origin main" >&2
  exit 1
else
  gh repo create "$OWNER/reel-studio" --public --source . --remote origin --push \
    --description "AI editor that turns food clips into an Instagram Reel (Claude API + ffmpeg)"
fi

say ".env"
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "  created .env from .env.example"
fi
# Folder paths are not secrets: fill them when empty and the folder exists.
python3 - "$HOME/projects/opus-build-day-make-reels" "$HOME/projects/reel-studio/input" <<'PY'
import os, re, sys
values = {"OLD_KIT_DIR": sys.argv[1], "REEL_FIXTURES_DIR": sys.argv[2]}
text = open(".env").read()
for key, path in values.items():
    line = re.search(r"^%s=[ \t]*(#.*)?$" % key, text, re.M)
    if not line:
        print("  %s already set" % key)
        continue
    if not os.path.isdir(path):
        print("  %s left empty: %s not found" % (key, path))
        continue
    text = text[:line.start()] + "%s=%s" % (key, path) + text[line.end():]
    print("  %s=%s" % (key, path))
open(".env", "w").write(text)
fixtures = sys.argv[2]
if os.path.isdir(fixtures):
    names = sorted(n for n in os.listdir(fixtures) if os.path.isdir(os.path.join(fixtures, n)) and not n.startswith("_"))
    print("  footage folders: %s (%d of 5 for STEP-04)" % (", ".join(names), len(names)))
PY

cat <<NEXT

Done. Next:
  1. Fill the keys:   open -e "$ROOT/.env"     (ANTHROPIC_API_KEY, GEMINI_API_KEY, STRIPE_SECRET_KEY)
  2. Start STEP-01:   cd "$ROOT" && claude --rc "reel main" --permission-mode plan
     Then paste:      Read CLAUDE.md, HANDOFF.md and docs/build/STEP-01.md. Plan STEP-01.
NEXT
