# Handoff — lane engine

Written by the engine lane only. Trimmed 16 Oct 2026 to the live items; older text is in git
history (`git log -p -- docs/handoff/engine.md`).

## Status
- STEP-04 closed by Kevin's decision (13 Oct, D79): ship the new engine to the friends beta, no
  more A/B rounds. Round 3 (eval/results/2026-10-13/ab.json): new picked 1 of 5; mean critic 21.4
  new vs 22.0 old; mean cost $0.42 vs $1.35. Clearest losses were inputs: `meat` had a landscape
  clip shown with blur fill; `mercadona` had 13.7 s of footage, under the 15 s minimum. Recorded
  in eval/AB-RESULT.md. The step04 gate still fails its picks rule (`new picked or tied in >= 3 of
  5`) by design: D44's A/B stays the bar for leaving the beta.
- A/B ledger: $14.51 of $20 paid across three rounds. No paid call since.
- Done earlier: STEP-02 (PR #2), STEP-03 (PR #5), STEP-04 harness (`make ab`, `make ab-pick`,
  `reel_studio/editor/ab*.py`) on PR #10.

## Next
- PR #10 merges once CI is green (`gh pr merge 10 --auto --squash`).
- STEP-05 waits on #10: PR #12 (film the speech fixtures; main adds google-genai to the ledger).
- If the beta shows the same losses: a length floor against sped-up cuts, mercadona's sound.

## Open follow-ups
- "At most four process steps" and "photo at most 1.2 s" pull against the recipe structure and
  against "payoff holds 2-3 s" when the only finished shot is a photo; the critic does not know
  the new rules; the grade rule is not always followed (creami natural, mercadona 0.5/0.9).
- Harness: REDO with the same name twice keeps only the last entry; the cross-day
  `superseded_paid_usd` pop has no test; `max_files` 1 divides by zero in `select_inputs`;
  `read_grade_preview` renders at `default_match` 0.6, so the editor never sees match 0.8 before
  choosing it; `files` is recorded per row, not per arm. Never repeat an identical REDO after a
  partial run: it pays finished arms again.
- STEP-03 left open: W6 the 1-hour cache TTL has no price row (`prices.toml`); W8 `--voice on`
  with a Gemini key keeps the voice with no transcript until STEP-05. Phase B: S7 codec names
  inline (`prepare.py`, `render_steps.py`); S8 small drifts; dead-air and blur warnings, the hook
  `""` rule and failing size/black-frame checks have no test; `test_edl_json_is_read_not_written`
  would pass if a new exit 2 appeared before the read.
- Review leftovers: a ProviderRejected critic call after a good render still aborts the order
  (S1); a caption escaped twice keeps one backslash (S2); a photo the process cannot read raises
  PermissionError while staging (not a MediaError); render outputs are not atomic (S2 phase B).
- `anthropic` `messages.stream` and httpx2 `MockTransport` uses wait in
  `eval/doc-ledger.pending.json` for main to copy into the ledger.

## For MAIN
- `docs/build/STEP-04.md:8,54` and `docs/build/README.md:14` still say $15; Kevin raised it to $20.
- `docs/DECISIONS.md` D35 still says `write_edl` is strict (EDITOR §4 corrected; Needs Kevin 20).
- D79 knock-ons: HANDOFF.md still says "STEP-04's gate (D44) before any deploy"; EDITOR.md §11
  is titled "The A/B before hosting (D44...)".

## Needs Kevin
Answered and kept because code cites them: 1. tonemap luma reference = SDR render of the same
pattern, ±15 % (9 Oct; `media.toml [prepare.tonemap].sdr_luma_tolerance`, `make_sdr_twin`).
Plan row 10: `qa.json` `hard_checks` keys are the kit's PASS/FAIL lines (`spec_text`,
`spec_clean`, `size_duration_text`, `size_duration_clean`, `no_black_frames`,
`text_in_safe_zone`); loudness stays a flag, the gate checks −14 ± 1 LUFS itself.

24. **D79 is not in `docs/DECISIONS.md`.** NIGHT.md asked ENGINE to add it; the lane guard refuses
    (`docs/DECISIONS.md belongs to lane 'main'`). Text ready in eval/AB-RESULT.md; MAIN or Kevin
    adds the row and marks D44 "superseded for the beta by D79".
5. EDITOR.md §1 says tonemap "zscale + hable"; the kit and the port use mobius (D46). Fix §1 or ask
   for hable.
10. `reel render` needs `ANTHROPIC_API_KEY` though it never calls the API (proposal: `MediaSettings`).
11. Assumption A2 says "1080p proxies"; cover scaling makes a landscape clip a 3414x1920 proxy.
13. Style photos are matched by substring (`vsco`, `look`, `ref`), so `refried_beans.jpg` vanishes
    (logged). Whole-word matching would change kit behaviour.
16. `audio.natural_db` no longer changes anything audible; remove it or keep it as a no-op.
20. Answered 11 Oct: the API refused strict `write_edl` (400 "The compiled grammar is too large"),
    so `write_edl` goes without `strict` (`tools.py` NOT_STRICT); read tools and `submit_review`
    stay strict.
21. Answered 11 Oct: `httpx2` declared in `[editor]`; `adapters/claude/client.py` imports it to catch
    `httpx2.TransportError` mid-stream, which the SDK does not wrap.

## Evidence lines
- 2026-10-13 round 3 rerun, our arm only: $1.6120; eval/results/2026-10-13/ab-runs.json.
- 2026-10-11 STEP-03 Sonnet rounds on creami: $1.4731 total; critic 23, 24, 21, 23 of 35.
- 2026-10-10 Editor image (CI, linux/amd64): built in 29 s, 1,264,698,610 bytes; `reel render`
  inside it exits 0 with every hard check true (tests/integration/editor/test_image.py).
- 2026-10-10 STEP-02 local gate on cf1def3: `GATE step02 PASS`; outputs 1080x1920, h264, 30/1,
  aac, -13.9 LUFS; input folder SHA-256 equal (D02).
