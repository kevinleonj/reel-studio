# STEP-09 — Friends beta

**Outcome:** friends make Reels with personal codes; Kevin sees, every week, how many Reels were made,
what they cost per style, how the critic scored them and what friends rated them.

Repository: the main checkout (`git rev-parse --show-toplevel` ends in `/reel/reel-studio`); do not leave it.
Settled: D05, D22, D55, D58, D59, D63. Spend comes from the $100 workspace limit.

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
uv run reelctl orders list --status running          # works against the cloud with Kevin's login
```
Branch `step-09-beta`.

## Tasks

1. **Stripe stays in test mode for the friends beta (D58).** Orders are €0, so nothing changes for a
   friend except Stripe's "test mode" label; no account activation or business details are needed.
   Live mode comes with paid orders (the "Later" list).
2. **Codes:** `reelctl codes create --name <friend> --expires <YYYY-MM-DD>` for each friend (Kevin picks
   the beta's end date; `max_redemptions` from `config/limits.toml` is a ceiling only, no per-person
   limit, D55).
3. **Weekly report:** `reelctl report --week` prints Reels by style, mean and worst critic total, mean
   friend rating, cost per Reel by style (from `cost.by_model`), failures by code, median duration.
   After the 10th cloud Reel, the median duration becomes the time estimate on the progress page
   (D16): a config value, set by Kevin.
4. **Feedback loop:** each week, the worst-rated Reel's `work/` folder is downloaded with `reelctl`
   before its 7-day deletion and reviewed; prompt changes go through `make eval` on the fixtures
   before deploy.
5. **Second opinion before the first code goes out:** reviewer agent on the live configuration
   (`make smoke`, IAM, budget, limits).

## Done when

- `python3 scripts/gates/step09.py` prints `GATE step09 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/main.md` and the pull request.
- 10 friends finished at least one Reel; the report pasted in HANDOFF.md under a heading `Weekly report`.
- A short list of what to change before paid orders (the "Later" list in `docs/DECISIONS.md`).
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.

Final message: five-line status board.
