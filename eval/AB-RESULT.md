# A/B result: new engine vs the old kit (STEP-04)

Source: `eval/results/2026-10-11/ab-runs.json`. Same files and order to both engines;
our critic judges both finished cuts.

| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |
|---|---|---|---|---|---|---|---|---|
| cookies | pending |  | 19 | 19 | 0.34 | 1.44 | 286 | 574 |
| creami | pending |  | 23 | 21 | 0.39 | 1.20 | 237 | 430 |
| meat | pending |  | 24 | 24 | 0.43 | 1.77 | 281 | 675 |
| mercadona | pending |  | 16 | 20 | 0.28 | 1.06 | 159 | 336 |
| pastav2 | pending |  | 23 | 22 | 0.47 | 1.20 | 371 | 510 |

Verdict: pending Kevin's blind picks (make ab-pick)

- `ok    mean critic new 21.0, old 21.2`
- `ok    gates lost by new: none`
- `ok    mean new cost $0.38`
- `ok    budget: $8.58 of $15.0`
