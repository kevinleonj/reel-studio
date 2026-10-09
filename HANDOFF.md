# HANDOFF

The main checkout's log and the status of every lane. Lanes write their own files in `docs/handoff/`.
Newest entry on top.

## Status board
- Done: starter kit v1.1 (docs, hooks, scanner, gates, lanes)
- Partly: —
- Blocked: —
- Not started: STEP-01 to STEP-09
- Next: STEP-00 (`bash scripts/dev/first-run.sh`), then STEP-01 in the main checkout

## Lanes
| Lane | Worktree | Steps | File |
|---|---|---|---|
| main | `~/projects/reel/reel-studio` | 01, 09 | this file |
| engine | `~/projects/reel/reel-studio-engine` | 02, 03, 04, 05 | `docs/handoff/engine.md` |
| web | `~/projects/reel/reel-studio-web` | 06, 07 | `docs/handoff/web.md` |
| cloud | `~/projects/reel/reel-studio-cloud` | 08 | `docs/handoff/cloud.md` |

## Needs Kevin
- Two more footage folders in `REEL_FIXTURES_DIR` before STEP-04 (5 needed, 3 present).

## Log
### 9 Oct 2026 — starter kit v1.1
- Before: kit v1 (Vite front end, a narrow literal test, hooks for one session).
- After: Astro (D71), analytics seam off (D75), hard-coded-value scanner (D76), Mac with three lanes (D77),
  a gate script per step (D78). Hooks: 465 self-checks under Python 3.9 and 3.13; scanner self-test 34/34;
  gates self-test 30/30.
- Follow-ups: STEP-00, STEP-01.
