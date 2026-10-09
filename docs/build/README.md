# How to build Reel Studio with Claude Code

Ten steps. After STEP-01, three lanes run in parallel, each in its own git worktree. Every step is one
session (two at most), one branch, one pull request that Kevin merges, and one gate script that decides
"done" (D78). A step is not done until its gate prints `GATE stepNN PASS`.

| Step | Lane | A person can now… | Gate | Paid API budget |
|---|---|---|---|---|
| 00 | Kevin | — | `scripts/dev/first-run.sh` prints all OK | $0 |
| 01 | main | Clone the repo and run `make ci` green | `scripts/gates/step01.py` | $0 |
| 02 | engine | Render a Reel from a hand-written edit list | `step02.py`: both MP4s meet the spec, input folder byte-identical | $0 |
| 03 | engine | Run `reel make ./clips` and get a Reel edited by Claude | `step03.py`: creami ≤ $1.20, critic passed, cache reads from request 2 | ≤ $5 |
| 04 | engine | Know whether the new engine is as good as the old kit | `step04.py`: A/B rules recomputed from `ab.json` | ≤ $15 |
| 05 | engine | Make long-take, talking and tutorial Reels | `step05.py` | ≤ $10 |
| 06 | web | Use the full website on the laptop | `step06.py`: `make prerelease`, live crawl and noindex checks | ≤ $3 |
| 07 | web | Redeem a test code and get a Reel, with limits and queue | `step07.py`: race tests, `reelctl` | ≤ $3 |
| 08 | cloud | Use the hosted beta from a phone | `step08.py`: policy, `deploy.yml`, `make smoke` | ≤ $3 |
| 09 | main | Friends make Reels | `step09.py` | from the $100 |

## Order

1. **STEP-01 alone**, in the main checkout `~/projects/reel/reel-studio`. Merge it.
2. **Then three lanes at once:** engine (02 → 03 → 04 → 05), web (06 → 07), cloud (08 tasks 1–6: policy
   checks, Terraform roots, `deploy.yml`, plans; no apply).
3. **Hosting waits for evidence:** Kevin applies the bootstrap root and the first deploy runs only after
   STEP-04's gate passed (D44) and STEP-07 is merged.
4. **STEP-09** after STEP-08, in the main checkout.

## Start a lane (Kevin, in Terminal)

```bash
cd ~/projects/reel/reel-studio && git switch main && git pull --ff-only
bash scripts/dev/lane.sh new engine                      # once per lane: ~/projects/reel/reel-studio-engine
bash scripts/dev/lane.sh start engine step-02-pipeline   # every step: fresh branch from origin/main
cd ~/projects/reel/reel-studio-engine
claude --rc "reel engine" --permission-mode plan
```

Then, inside Claude Code:
1. `Read CLAUDE.md, docs/handoff/engine.md and docs/build/STEP-02.md. Plan STEP-02.`
2. Approve the plan only if every task names its failing test first. Switch to auto mode when you approve
   (Shift+Tab), so the session runs without permission prompts; the hooks still block the dangerous actions.
3. Set the goal (one line):
   `/goal python3 scripts/gates/step02.py prints "GATE step02 PASS" in this session, the pull request is open, and docs/handoff/engine.md is updated. If something blocks the work, write it under "Needs Kevin" in docs/handoff/engine.md and stop. Stop after 80 turns at most.`
4. Watch from the Claude app on your phone: Remote Control lists the session as "reel engine".
5. When the gate passes and CI is green, review and merge the pull request on GitHub. `/clear` before the
   next step, then `lane.sh start` again with the next branch name.

Branch names: `step-01-skeleton`, `step-02-pipeline`, `step-03-editor-loop`, `step-04-ab`,
`step-05-speech`, `step-06-website`, `step-07-gate`, `step-08-cloud`, `step-09-beta`.
Session names: `reel main`, `reel engine`, `reel web`, `reel cloud`.

## What keeps the lanes apart

- **Paths:** each lane edits only its own paths plus a short shared list (`.claude/lanes.json`); the hooks
  block the rest and the Stop hook checks committed files too. A need outside the lane goes under
  "Needs Kevin" in the lane's handoff file.
- **Dependencies:** STEP-01 declares every Python dependency. A lane that needs another one writes the
  reason in its handoff file. On a `uv.lock` conflict: take main's file, run `uv lock`, never hand-edit.
- **Merges:** before opening a pull request the session runs `git fetch origin && git merge origin/main`
  and `make ci` again. `docs/FACTS.md` and `docs/LESSONS.md` merge by union (`.gitattributes`).
- **Ports:** only the web lane starts containers (Firestore emulator, Mailpit, `make up`).
- **Memory:** the Mac has 16 GB. Three sessions and Docker fit; if Activity Monitor shows red memory
  pressure, pause the cloud lane first.

## Kevin's part

Plan approvals, "Needs Kevin" answers and merges in every lane; the blind picks in STEP-04; filming the
speech clips for STEP-05; two more footage folders before STEP-04; the bootstrap apply and the phone test
in STEP-08. Status at a glance: `bash scripts/dev/lane.sh status`.

## When something goes wrong

- The same bug survived two fixes: `/clear`, restate the bug in one paragraph with the failing test
  name, and ask for a root-cause table before any fix (AUDIT THEN FIX).
- A decision blocks the work: Claude Code writes it under "Needs Kevin" in the lane's handoff file and
  stops. Only Kevin changes `docs/DECISIONS.md` (start that session with `REEL_ALLOW_DECISION_EDIT=1`).
- A gate is wrong: only Kevin changes it (`REEL_ALLOW_GATE_EDIT=1`), with the reason in the commit.
- Before step 08's first apply and before the first friend gets a code, run the reviewer agent:
  `Use the reviewer agent on the diff since the last tag.`
