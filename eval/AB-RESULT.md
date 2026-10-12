# A/B result: new engine vs the old kit (STEP-04)

Source: `eval/results/2026-10-11/ab.json`. Same files and order to both engines;
our critic judges both finished cuts.

| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |
|---|---|---|---|---|---|---|---|---|
| cookies | old | Both are quite bad and none show the finished cookies, but x flows better | 19 | 19 | 0.34 | 1.44 | 286 | 574 |
| creami | old | Y had static images for too long, static images are fine, but it slowed down the flow so much | 23 | 21 | 0.39 | 1.20 | 237 | 430 |
| meat | old | better storytelling, while y showed too many steps with my arms | 24 | 24 | 0.43 | 1.77 | 281 | 675 |
| mercadona | tie | good editing on both | 16 | 20 | 0.28 | 1.06 | 159 | 336 |
| pastav2 | new | y the image quality and color was off | 23 | 22 | 0.47 | 1.20 | 371 | 510 |

Verdict: FAIL

- `FAIL  new picked or tied in 2 of 5`
- `ok    mean critic new 21.0, old 21.2`
- `ok    gates lost by new: none`
- `ok    mean new cost $0.38`
- `ok    budget: $8.58 of $15.0`

What to tune: read each lost fixture's weakness in ab-runs.json, change the prompts
for it, and rerun only those fixtures (`make ab REDO=<names>`; a plain `make ab`
resumes a run that stopped).
