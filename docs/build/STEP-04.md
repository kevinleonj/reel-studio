# STEP-04 — The A/B: is the new engine as good as the old kit?

**Outcome:** a written, evidence-backed answer to "does our own loop edit as well as the Agent SDK
kit?", with cost. Nothing is hosted until this gate passes (D44).

Lane **engine**: the worktree `~/projects/reel/reel-studio-engine` (`git rev-parse --show-toplevel` ends in
`/reel-studio-engine`); do not leave it. Handoff file: `docs/handoff/engine.md`.
Settled: D03, D33, D39, D44, `docs/EDITOR.md` §11. Paid budget: ≤ $15.

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
grep -o '^\(OLD_KIT_DIR\|REEL_FIXTURES_DIR\)=' .env       # both present
python3 -c "import pathlib,re;t=pathlib.Path('.env').read_text();d=re.search(r'^REEL_FIXTURES_DIR=(\S+)',t,re.M).group(1);print(sorted(p.name for p in pathlib.Path(d).iterdir() if p.is_dir() and not p.name.startswith('_')))"   # 5 names
```
Running the old kit with Kevin's own key is allowed (F01: the end user is Kevin). Branch `step-04-ab`.

## Tasks

1. **Harness** `eval/ab.py`: for each fixture, run the new engine (`reel make`) and the old kit (its own
   command and virtual environment in `OLD_KIT_DIR`, never imported into our package). Fixtures are the
   folders in `REEL_FIXTURES_DIR` whose names do not start with `_` (exactly 5). Write
   `eval/results/<YYYY-MM-DD>/ab.json`: `fixtures` = list of {`name`, `pick` (`new`|`old`|`tie`), `reason`,
   `new` {`critic_total`, `passed`, `cost_usd`, `wall_s`, `outputs`}, `old` {same}}. The gate recomputes
   the verdict from this file.
2. **Same judge.** Judge every output, old and new, with our critic (`docs/EDITOR.md` §6), so the
   comparison does not depend on either engine's own critic.
3. **Blind pick.** `make ab-pick` shows each pair as X and Y in random order (local HTML page or
   terminal player commands), records Kevin's pick and a one-line reason, then reveals the mapping.
4. **Report** `eval/AB-RESULT.md`: table per fixture (critic totals, Kevin's pick, cost, time), the gate
   verdict, and what to tune if it failed.
5. **Optional experiments, only if budget remains and the gate passed:** effort `medium` (D33) and the
   Haiku drop-files pass (D39) on the same fixtures, judged the same way. They change defaults only
   with Kevin's yes in HANDOFF.md.

## Gate (from `docs/EDITOR.md` §11)

New engine picked or tied in ≥ 3 of 5; mean critic total ≥ old − 1; no fixture fails the gates where
the old one passed; mean cost ≤ $1.20. If it fails: tune prompts, rerun only the failing fixtures, and
do not start step 06.

## Done when

- `python3 scripts/gates/step04.py` prints `GATE step04 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/engine.md` and the pull request.
- `eval/AB-RESULT.md` committed with the table and the verdict; Kevin's picks recorded.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/engine.md`.)

STOP if the paid budget would pass $15. Final message: five-line status board, the verdict line, PR link.
