#!/bin/bash
# Parallel lanes as sibling git worktrees (docs/build/README.md, D77). Kevin runs this, not Claude Code.
#   bash scripts/dev/lane.sh new <lane>             once: ../reel-studio-<lane> with .lane and a .env link
#   bash scripts/dev/lane.sh start <lane> <branch>  each step: fresh branch from origin/main in that lane
#   bash scripts/dev/lane.sh status                 every checkout: branch, commits ahead/behind main, changes
# Written for macOS /bin/bash 3.2: no arrays beyond "$@", no mapfile, no ${var,,}.
set -eu

die() { printf 'lane.sh: %s\n' "$*" >&2; exit 1; }

MAIN="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run it from the main checkout"
[ -f "$MAIN/.claude/lanes.json" ] || die "$MAIN has no .claude/lanes.json: run it from the main checkout"
[ ! -f "$MAIN/.lane" ] || die "this is a lane worktree; run it from the main checkout"
PARENT="$(dirname "$MAIN")"
NAME="$(basename "$MAIN")"

valid_lane() {
  case "$1" in
    engine|web|cloud) return 0 ;;
    *) die "unknown lane '$1' (engine, web or cloud)" ;;
  esac
}

lane_dir() { printf '%s/%s-%s' "$PARENT" "$NAME" "$1"; }

setup_checkout() {
  # make setup exists from STEP-01 on; before that there is nothing to install.
  if [ -f "$1/Makefile" ] && grep -q '^setup:' "$1/Makefile"; then
    (cd "$1" && make setup)
  fi
}

cmd="${1:-}"
case "$cmd" in
  new)
    [ $# -eq 2 ] || die "usage: lane.sh new <lane>"
    lane="$2"; valid_lane "$lane"
    dir="$(lane_dir "$lane")"
    [ ! -e "$dir" ] || die "$dir already exists"
    git -C "$MAIN" fetch --quiet origin
    git -C "$MAIN" worktree add --quiet -b "lane/$lane" "$dir" origin/main
    printf '%s\n' "$lane" > "$dir/.lane"
    [ -f "$MAIN/.env" ] || die "create $MAIN/.env first (first-run.sh)"
    ln -s "$MAIN/.env" "$dir/.env"
    setup_checkout "$dir"
    printf 'Lane %s ready at %s\nNext: bash scripts/dev/lane.sh start %s <branch>\n' "$lane" "$dir" "$lane"
    ;;
  start)
    [ $# -eq 3 ] || die "usage: lane.sh start <lane> <branch>"
    lane="$2"; branch="$3"; valid_lane "$lane"
    dir="$(lane_dir "$lane")"
    [ -d "$dir" ] || die "no lane at $dir: run 'lane.sh new $lane' first"
    [ -z "$(git -C "$dir" status --porcelain)" ] || die "$dir has uncommitted changes; finish or stash them first"
    git -C "$dir" fetch --quiet origin
    if git -C "$dir" show-ref --verify --quiet "refs/heads/$branch"; then
      die "branch $branch already exists; pick the next step's branch name"
    fi
    git -C "$dir" switch --quiet -c "$branch" origin/main
    setup_checkout "$dir"
    printf 'Lane %s on %s (from origin/main)\nNext: cd %s && claude --rc "reel %s" --permission-mode plan\n' \
      "$lane" "$branch" "$dir" "$lane"
    ;;
  status)
    git -C "$MAIN" fetch --quiet origin || true
    for dir in "$MAIN" "$(lane_dir engine)" "$(lane_dir web)" "$(lane_dir cloud)"; do
      [ -d "$dir" ] || continue
      lane="main"; [ -f "$dir/.lane" ] && lane="$(cat "$dir/.lane")"
      branch="$(git -C "$dir" branch --show-current)"
      counts="$(git -C "$dir" rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo '? ?')"
      behind="$(printf '%s' "$counts" | cut -f1)"; ahead="$(printf '%s' "$counts" | cut -f2)"
      changes="$(git -C "$dir" status --porcelain | wc -l | tr -d ' ')"
      printf '%-7s %-24s ahead %-4s behind %-4s changed files %s\n' "$lane" "$branch" "$ahead" "$behind" "$changes"
    done
    ;;
  *)
    die "usage: lane.sh new <lane> | start <lane> <branch> | status"
    ;;
esac
