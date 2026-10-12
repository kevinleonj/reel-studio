# A/B result: new engine vs the old kit (STEP-04)

**Kevin: run `make ab-pick` before reading this page; the scores would**
**anchor the blind picks.**

Source: `eval/results/2026-10-12/ab-runs.json`. Same files and order to both engines;
our critic judges both finished cuts.

| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |
|---|---|---|---|---|---|---|---|---|
| cookies | pending |  | 19 | 19 | 0.37 | 1.44 | 301 | 574 |
| creami | pending |  | 24 | 21 | 0.41 | 1.20 | 344 | 430 |
| meat | pending |  | 23 | 24 | 0.42 | 1.77 | 325 | 675 |
| mercadona | pending |  | 16 | 20 | 0.28 | 1.06 | 159 | 336 |
| pastav2 | pending |  | 23 | 22 | 0.47 | 1.20 | 371 | 510 |

Verdict: pending Kevin's blind picks (make ab-pick)

- `ok    mean critic new 21.0, old 21.2`
- `ok    gates lost by new: none`
- `ok    mean new cost $0.39`
- `ok    budget: $8.61 of $15.0`
- every paid attempt, superseded ones included: ledger $9.78
