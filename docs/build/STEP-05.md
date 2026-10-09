# STEP-05 — Speech: long takes, talking clips, tutorials

**Outcome:** `reel make ./clips --style talking` (and `long_take`, `tutorial`) cuts between words, keeps
the best take of each line and keeps the voice.

Lane **engine**: the worktree `~/projects/reel/reel-studio-engine` (`git rev-parse --show-toplevel` ends in
`/reel-studio-engine`); do not leave it. Handoff file: `docs/handoff/engine.md`.
Settled: D10, D14, D40, D41, `docs/EDITOR.md` §5. No faster-whisper in v1 (D40). Paid budget ≤ $10.

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
grep -o '^GEMINI_API_KEY=' .env
uv run python -c "import google.genai as g; print(g.__version__)"     # 2.29 or later (F38)
```
Before writing the call, query Context7 for `google-genai` transcription with word timestamps and read
https://ai.google.dev/gemini-api/docs/transcribe again; record the request shape in FACTS.md (F37).
Branch `step-05-speech`.

## Tasks

1. **Transcriber port** with a fake. Real adapter: `gemini-3.5-transcribe`, word timestamps on, no
   language code (auto-detect), one request per clip, rejects audio over 20 min (D10); pre-call cost
   check through the meter (§8). Test with a recorded response: words, start and end times parsed;
   a clip without audio is skipped.
2. **Packed transcript** (§5): phrases split at gaps ≥ 400 ms, gap length shown. Golden test on a
   recorded transcript.
3. **Speech-cut validation** in `write_edl`: cuts inside speech must land in gaps ≥ 400 ms, or
   150–400 ms with `visual_check: true`; error messages name the nearest valid gap. Renderer pads
   30–200 ms and fades 30 ms at every cut (F59). Tests on synthetic word lists.
4. **Speech check in QA:** transcribe the rendered speech once, compare word by word with the edit
   list's `quote` fields, put differences in `qa.json` for the critic.
5. **Prompts:** `styles/story_trim.md`, `styles/talking.md`, `structures/story.md`, `talk.md`,
   `tutorial.md`; the voice default per style from `config/styles.toml`.
6. **Fixtures (Kevin films them, about 10 minutes in total):** one long take; two talking clips in
   Spain Spanish with at least one stutter and one repeated line; one tutorial. Name the fixture folders
   `long_take`, `talking_es1`, `talking_es2`, `tutorial` (the gate matches these prefixes). Run each once
   with Sonnet through `make eval`.
7. **Stutter test (A4):** for the Spanish clips, record in `eval/SPEECH-RESULT.md` whether the
   transcript caught the stutter and the retake, which take was kept, and any wrong word in the
   speech check. If Spanish fails, write the failing words; do not switch providers without Kevin.

## Done when

- `python3 scripts/gates/step05.py` prints `GATE step05 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/engine.md` and the pull request.
- Each speech fixture passes the critic gates; costs listed per fixture.
- `eval/SPEECH-RESULT.md` committed.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/engine.md`.)

STOP if the paid budget would pass $10. Final message: five-line status board, then the PR link.
