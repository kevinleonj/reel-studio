# A/B result: new engine vs the old kit (STEP-04)

**Kevin: run `make ab-pick` before reading this page; the scores would**
**anchor the blind picks.**

Source: `eval/results/2026-10-13/ab-runs.json`. Same files and order to both engines;
our critic judges both finished cuts.

| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |
|---|---|---|---|---|---|---|---|---|
| cookies | pending |  | 21 | 23 | 0.46 | 1.51 | 584 | 740 |
| creami | pending |  | 23 | 21 | 0.43 | 1.20 | 297 | 430 |
| meat | pending |  | 23 | 24 | 0.48 | 1.77 | 462 | 675 |
| mercadona | pending |  | 17 | 20 | 0.24 | 1.06 | 219 | 336 |
| pastav2 | pending |  | 23 | 22 | 0.47 | 1.20 | 371 | 510 |

Verdict: pending Kevin's blind picks (make ab-pick)

- `ok    mean critic new 21.4, old 22.0`
- `ok    gates lost by new: none`
- `ok    mean new cost $0.42`
- `ok    budget: $8.82 of $20.0`
- every paid attempt, superseded ones included: ledger $14.51
