# A/B result: new engine vs the old kit (STEP-04)

Source: `eval/results/2026-10-13/ab.json`. Same files and order to both engines;
our critic judges both finished cuts.

| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |
|---|---|---|---|---|---|---|---|---|
| cookies | old | Smarter selection of snippets | 21 | 23 | 0.46 | 1.51 | 584 | 740 |
| creami | old | bETTER flow | 23 | 21 | 0.43 | 1.20 | 297 | 430 |
| meat | old | No weird horizontal image out of nowhere | 23 | 24 | 0.48 | 1.77 | 462 | 675 |
| mercadona | old | x WAS way too short and pointless | 17 | 20 | 0.24 | 1.06 | 219 | 336 |
| pastav2 | new | Color is better | 23 | 22 | 0.47 | 1.20 | 371 | 510 |

Verdict: FAIL

- `FAIL  new picked or tied in 1 of 5`
- `ok    mean critic new 21.4, old 22.0`
- `ok    gates lost by new: none`
- `ok    mean new cost $0.42`
- `ok    budget: $8.82 of $20.0`
- every paid attempt, superseded ones included: ledger $14.51

What to tune: read each lost fixture's weakness in ab-runs.json, change the prompts
for it, and rerun only those fixtures (`make ab REDO=<names>`; a plain `make ab`
resumes a run that stopped).

## Kevin's decision, 13 Oct 2026 (D79)

Ship the new engine to the friends beta anyway; no more A/B rounds. Round 3: Kevin picked
the new engine in 1 of 5; mean critic 21.4 new vs 22.0 old; mean cost $0.42 new vs $1.35 old.
The clearest losses were inputs: `meat` had a landscape clip shown with blur
fill, and `mercadona` had 13.7 s of footage, under the 15 s minimum. D79 supersedes D44 for
the beta only; this A/B gate stays the bar for leaving the beta.
