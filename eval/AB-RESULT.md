# A/B result: new engine vs the old kit (STEP-04)

Source: `eval/results/2026-10-12/ab.json`. Same files and order to both engines;
our critic judges both finished cuts.

| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |
|---|---|---|---|---|---|---|---|---|
| cookies | old | Better colors and better flow | 22 | 23 | 1.14 | 1.51 | 469 | 740 |
| creami | old | I like the zoom in and the flow | 23 | 21 | 0.81 | 1.20 | 290 | 430 |
| meat | old | y | 23 | 24 | 0.86 | 1.77 | 349 | 675 |
| mercadona | old | y | 16 | 20 | 0.28 | 1.06 | 159 | 336 |
| pastav2 | new | Better colors | 23 | 22 | 0.47 | 1.20 | 371 | 510 |

Verdict: FAIL

- `FAIL  new picked or tied in 1 of 5`
- `ok    mean critic new 21.4, old 22.0`
- `ok    gates lost by new: none`
- `ok    mean new cost $0.71`
- `ok    budget: $10.30 of $15.0`
- every paid attempt, superseded ones included: ledger $12.90

What to tune: read each lost fixture's weakness in ab-runs.json, change the prompts
for it, and rerun only those fixtures (`make ab REDO=<names>`; a plain `make ab`
resumes a run that stopped).
