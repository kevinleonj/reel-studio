# Handoff — lane engine

Written by the engine lane only. Newest entry on top.

## Status board
- Done: STEP-03 merged (PR #5, 11 Oct 19:28 UTC; gate 12 of 13, only the model-judged
  `critic.passed` failed after 3 rounds: 24, 21, 23 of 35, gate 26; $1.4731 of $5). STEP-04 tasks 1,
  2 and 4 built on `step-04-ab`: `make ab` (both engines, same files, our critic judges both, budget
  guard) and `make ab-pick` (blind X/Y picks, ab.json, eval/AB-RESULT.md). Round 1 (11 Oct,
  $8.58): Kevin's picks gave new 1, tie 1, old 3, so the gate failed on the picks rule only
  (eval/results/2026-10-11/ab.json). Round 2 (12 Oct): the editor prompt now follows Kevin's
  reasons (finished food shown and last, photos at most 1.2 s and never two in a row, at most four
  process steps and no hands-filling-frame shots); only our engine reran on cookies, creami and
  meat (`REDO=<name>:new`); the kit's 11 Oct cuts are kept. A first pass ($1.20) dropped every
  step label, so the rule now says it limits shots, not labels, and our arm ran again ($1.17):
  4, 4 and 6 labels, no two photos in a row, photos at most 1.2 s, each ends on its payoff.
  Cookies: the first 15 files by name end before the cookies come out of the oven (IMG_0499,
  0500, 0502 are left out), for both engines, so no prompt can show the finished cookies. A
  spread file choice fixed that (3d5f3da, both engines rerun, $1.95) but replaced the kit's 11 Oct
  cut, which Kevin's goal keeps; it was reverted (f879cac) and the cookies row restored to our
  round-2 cut and the kit's 11 Oct cut. The $1.95 stays on the ledger (`superseded_paid_usd`).
  Ledger $12.90 of $15; a fixture's new cost in the report includes every same-day pass.
- Open from the round 2 review (not done): "at most four process steps" and "photo at most 1.2 s" pull against the recipe structure
  and the craft reference, and the critic does not know the new rules; REDO with the same name
  twice keeps only the last entry; the prompt tests pin phrases, not whole rules; the cross-day
  side-only redo has no saved test. meat and pastav2 rows keep their first-15 files; a later
  REDO on them would pick the spread files, so rerun both sides there, never one.
- Needs Kevin's hands: round 2 blind picks. Cookies still cannot show its finished tray unless
  you approve a new file choice and a kit rerun (about $1.9, it fits the $15). For the picks, in
  a terminal: `cd ~/projects/reel/reel-studio-engine
  && make ab-pick`, open the page it prints, type x, y or tie and a reason for each of the 5
  fixtures (mercadona and pastav2 are the round 1 pairs again). Read eval/AB-RESULT.md only after.
  PR #10 waits for the picks: the step04 gate reads the newest ab.json.
- Waits on #10 and Kevin: STEP-05 on PR #12 (see that branch's handoff: film the speech
  fixtures; main adds google-genai to the doc ledger)
- Ledger: anthropic `messages.stream` and httpx2 `MockTransport` uses added to `eval/doc-ledger.pending.json`

## Decided by standing orders
- 11 Oct, STEP-04: the A/B fixtures are cookies, creami, meat, mercadona, pastav2 (STEP-04 says
  exactly 5; REEL_FIXTURES_DIR holds 8). Left out: orderinginspanish (speech, STEP-05), pasta (same
  dish as pastav2, half photos), melocotonjuice (one 9 s clip). The kit takes at most 15 files, so
  both engines get the same first 15 (videos first, by name). Order style montage for all; the kit
  gets no style. Undo: edit `limits.toml [eval.ab]`.
- 11 Oct, STEP-04: the harness lives in `reel_studio/editor/ab*.py` (STEP-04 names `eval/ab.py`;
  the package keeps it under mypy, ruff and the unit tests). Undo: move the files.
- 11 Oct, STEP-04: one order for both engines (montage, 30 s, English, voice off), given to the
  kit as `--context`; one judge (`ab_judge.CriticJudge`, our QA sheets + our critic) scores both
  finished cuts; the new engine's in-loop score is kept apart as `loop_critic_total`. Undo: revert
  0ca9696.
- 11 Oct, STEP-04 money rules: kit cap `kit_run_cap_usd` 2.5 per run; `judge_reserve_usd` 0.15 kept
  free; a ledger summed from every ab-runs.json (a rerun never spends twice); an arm in flight is
  on the ledger at its cap; a kit run refused for its key or billing stops the harness. `make ab`
  resumes, `ONLY=` limits it, `REDO=` reruns finished fixtures after a tune (it pays the kit again).
  Undo: `limits.toml [eval.ab]`.
- 11 Oct: non-spend, non-transient API errors (bad key, billing, bad request) raise a new
  `ProviderRejected` (code `provider_rejected`) instead of a raw SDK error, and the CLI logs them as
  one line. Why: the Tier 0 user saw a traceback. Undo: revert e109405.
- 11 Oct: round 3 removed the round-2 cut rules (variety, brightness order, last shot) after round 2
  scored 21 against round 1's 24 with a 14 s cut. Undo: revert 369f1a9 (restores them).
- 11 Oct: the soft-window column is removed (empty on real footage; its floor did not match
  QA's) and the blur rule tells the editor to check the hook, peak and payoff with read_strip.
  Undo: restore the column by hand; reverting ce060a3 would also bring back the 100x brightness.
- 11 Oct: a refused request keeps up to `anthropic.toml error_message_max_chars` = 300 characters
  of the provider's message (enough for the workspace-key error, 207 characters). Undo: lower it.
- Not done, recorded: a critic call refused by the provider (ProviderRejected) after a good
  render still aborts the order (review S1); a caption escaped twice (backslash backslash n) keeps
  one backslash (S2); the untyped-schema test walks property nodes only (S3).
- 11 Oct: an unjudged first render ships with weakness "not judged: <code>" and `critic.total`
  null in result.json (0 in the eval result, where the gate wants a number). Undo: revert 991fe50.

## For MAIN
- `docs/EDITOR.md` §2 lists the brief's inventory: add brightness (mean luma 0-255 with QA's
  luma_jump), every format's length range with the order target, and the text reading time.
- `web/src/copy/en.json` `failed.messages`: add `"provider_rejected": "Something broke while
  planning. Kevin has been notified."` (a refused request is our key or billing, not the user's
  footage), and add `ErrorCode.PROVIDER_REJECTED` to `FAILED_CODES` in
  `tests/contract/test_web_copy.py`.
- `docs/DECISIONS.md` D35 and `docs/EDITOR.md` §4 still say `write_edl` is strict; it is not since
  11 Oct (F211, Needs Kevin 20). A line there stops a later session from turning it back on.

## Needs Kevin
Answered 9 Oct 2026 (TONIGHT.md): 1. luma reference = SDR render of the same pattern, ±15 %
(changed from 10 % at 22:56; `media.toml [prepare.tonemap].sdr_luma_tolerance`); 2. new `sheets.py` per D38,
`limits.toml [sheets].near_duplicate_ssim = 0.93` (origin `qa.py:31`); 3. `hardcode-ok` markers stay;
4. kit `.ruff_cache` deleted by Claude at 22:50, kit equals the pre-session snapshot again (2,648 files,
byte-identical; read with Read/`rg` only from now on); 6. main added numpy, opencv-python-headless,
pillow-heif and scenedetect-headless to `[editor]` in STEP-01; 7. main added `ffmpeg_path`/`ffprobe_path`
to `EditorSettings`; 9. STEP-01 merged (6089989). Open:

5. **EDITOR.md §1 says tonemap "zscale + hable"; the kit uses mobius** (`prep.py:45`,
   `media.toml [prepare.tonemap]`). The port keeps mobius per D46. Correct EDITOR §1, or say hable is wanted.
10. **`reel render` needs `ANTHROPIC_API_KEY` set though it never calls the API.** `EditorSettings`
    (main's `settings.py`) requires the key, so a render-only run, the image test and the cloud render
    job must carry it. Proposal for main: a `MediaSettings` class with `ffmpeg_path`/`ffprobe_path` that
    `EditorSettings` extends; `reel render` would then read only `MediaSettings`.
11. **Assumption A2 says "1080p proxies".** The kit's cover scaling (`prep.py:61-63`, kept per D46) makes a
    landscape 1920x1080 clip a 3414x1920 proxy, so a landscape proxy holds about 3x the pixels A2 assumes.
    A2's wording or the proxy rule needs your call before STEP-05 measures memory.
12. **Review verdict file.** The phase A reviewer could not write the review verdict file under the
    protected `.claude/` folder (lane guard: it belongs to main). Before code reviews feed the Stop gate,
    add it and the doc ledger to `shared.paths` in the lanes file (protected).
13. **Style photos are matched by substring (kit `grade.py:33`, kept per D46).** Any image whose name
    contains `vsco`, `look` or `ref` is treated as a colour reference and left out of the Reel, so
    `refried_beans.jpg` or `outlook.jpeg` silently disappear (the phase B review reproduced it). Each
    such file is now logged. Whole-word matching would change kit behaviour: your call.
14. **CI time.** The full suite runs four prepare passes and two full renders, plus the image build and
    an in-container render, inside the protected workflow's 20-minute job. Locally: 2 min wall,
    about 11 CPU-minutes. If the first CI run comes close to 20 minutes, the workflow timeout (protected)
    or a shared render fixture is the lever.
15. **I pushed `step-02-pipeline` and opened PR #2 at about 06:00 UTC, after TONIGHT.md had changed to
    "No push tonight".** When I last read the engine section (the ±15 % update), it still said "push,
    `gh pr create`"; I did not re-read it before pushing. The PR is open, not a draft, CI green; nothing
    else was pushed afterwards. Later commits on `step-02-pipeline` (the image ENV test) and all of
    `step-03-editor-loop` are local only. Close, keep or update #2 as you prefer.
16. **`audio.natural_db` no longer changes anything you can hear.** REVIEW-FIXES item 4: loudness pass 1
    now measures after the same `volume=natural_db` that pass 2 applies, so the Reel lands on -14 LUFS
    for any `natural_db` (it was -19.9 at -6). The loudnorm that follows undoes any whole-Reel gain, so
    the field only mattered as a bug. In the kit it made room under music; without music (D02, D42) it
    has no purpose. The field stays (D46: the kit schema unchanged). Remove it from the schema and the
    prompt, or keep it as a no-op: your call.
17. Answered 10 Oct: #2 merged; you copied `anthropic`, `httpx2`, `jinja2` into the doc ledger; paid
    runs: Haiku once, then Sonnet once, through `make eval` only.
18. **The `.env` Anthropic key is not scoped to a workspace.** The first `make eval MODEL=haiku` stopped
    at its first (free) `count_tokens` call: 400 "This API key is not scoped to a workspace, so this
    request must include the anthropic-workspace-id header" ($0.00 spent; the run's record is
    `eval/results/2026-10-10/creami-haiku.json`). Your choice (10 Oct): a new key created inside
    workspace `reel-studio`, as D59 and ARCHITECTURE §5 say. Same check applies to
    `CLOUD_ANTHROPIC_API_KEY` before STEP-08's job runs. Done 11 Oct: the new key works.
19. **`make ci` fails on this Mac in `ci-cloud`:** Terraform 1.16.1 installed, `infra/*/versions.tf`
    pins `= 1.16.5`. Every engine check passes. Done 11 Oct: 1.16.5, tflint, trivy installed.
20. **Strict `write_edl` and the API's schema-complexity limits (F208).** The structured-outputs page
    allows 24 optional and 16 union-typed parameters across all strict tools per request. Counting
    top-level properties the five editor tools have 13 and 5; counting nested ones (Segment's many
    optional fields) 48 and 30. The page does not say which count applies; the first real request
    decides it (a 400 is not billed). If it is refused, D35 (strict `write_edl`) and D46 (kit schema
    unchanged) conflict, and the cheapest way out is `strict: false` on `write_edl` only (the
    validator already returns every violation): your call. Answered 11 Oct and applied: the API
    refused the strict `write_edl` with 400 "The compiled grammar is too large" (not billed), so
    `write_edl` goes without `strict` (`tools.py` NOT_STRICT); the read tools and `submit_review`
    stay strict. Before that, a second unbilled 400 found `Audio.music` offered as an untyped `{}`
    schema; it is no longer offered (the validator still refuses it, D02).
21. **Declare `httpx2` in pyproject (main lane).** `adapters/claude/client.py` now imports it to catch
    a connection that drops mid-stream (`httpx2.TransportError`), which the SDK does not wrap once the
    body is being read. It is anthropic's own HTTP layer, already in uv.lock at 2.13.1; the rule is that
    a dependency lands in pyproject with its first import. Run `uv add --optional editor
    "httpx2>=2.13.1"`. Alternative that lost: non-streaming `create` with an explicit timeout, which
    keeps the SDK's wrapping but is what the errors page warns against for long replies.
    11 Oct: MAIN declares it on main; the engine branch does not wait.
22. Answered 11 Oct: option (a), up to 3 Sonnet runs. Done; record below.
23. Done 11 Oct (e109405, 991fe50): captions get real line breaks at `write_edl`; every render's
    review is kept (`reviews` in result.json and in the eval result); the untyped-schema test looks
    for nodes without type/$ref/anyOf/enum/const; refused requests are one log line
    (`ProviderRejected`); a first render the critic cannot judge ships unjudged.

### Critic record for STEP-04 (creami, Sonnet editor and critic)
| Run | Prompt | Cost | Render 1 | Render 2 | Cut |
|---|---|---|---|---|---|
| 0 (10-11 06:47) | STEP-03 as built | $0.3444 | 23 | <= 23 (not saved) | 17.9 s |
| 1 (17:45) | + length targets, soft windows, no near-duplicates, text off labels | $0.3221 | 24 | 24 | 19.7 s |
| 2 (17:51) | + variety, brightness order, strongest last shot | $0.3424 | 21 | 21 | 14.1 s |
| 3 (17:57) | round-2 rules removed; + QA reading time in the brief | $0.4219 | 22 | 23 | 15.2 s, format `other` |

Scores never went above 3 on retention, peak, craft and share; hook was 4 except in run 2. The
issues every run repeats:
- Repeated finished-product shots in the middle (same pink pint or scoop, similar angles, 6-8 s).
  The fixture has 7 videos and 7 photos, mostly of the finished tub.
- Brightness jumps of 23-56 at cuts (0..255). The review measured the cause on the saved
  proxies: raw clips differ by at most 28 and the grade moves segments only -5..+8; the big jumps
  come from the editor's own zoomed crops (zoom 1.3-1.5 into a bright area, stills and video). A
  `write_edl` warning computed on the cropped proxy would give the editor the number before a
  render.
- No blending step: raw fruit to finished tub in one cut (the fixture has no blending clip).
- The ending repeats the hook (spoon in tub) instead of a bigger payoff.
- The hook cuts to the soft bag shot with a hand over the print; text over packaging.
Rounds 2 and 3 sent the editor a brightness column 100 times too large under a "0-100"
label (review C1, fixed after the runs: L20), and each score comes from one run, so 24, 21 and
23 cannot be told from the critic's own noise; the review suggests re-judging one saved render
twice (about $0.06 each) before crediting a rule. The length check only compares with the
format's range: rounds 2 and 3 chose `other` (15-50 s) for 14.1 s and 15.2 s cuts against a 30 s
order; the brief no longer says "choose the format first", and a warning on distance from the
order target is open. The soft-window column was empty on the real footage (its floor was not
QA's), so it is gone (ce060a3; reverting it would also bring back the 100x brightness). Open questions for the A/B:
whether the kit's editor scores higher on the same footage, whether the critic is too strict for
thin footage (every run is footage-limited by its own account).
Plan notes kept from the answered items: fonts (Poppins-Bold.ttf + OFL.txt) ship as package data
under `reel_studio/editor/media/fonts/`, no host-font fallbacks. Sheets failing case:
`test_sheet_is_1536x864_with_16_tiles` fails against a port of kit `build_sheets` (`prep.py:167-221`,
1980 px wide); `sheets.py` reuses the kit's scene detection (`prep.py:119-122`) and SSIM (`qa.py:43-51`).

## Evidence lines (the gates read these)
- 2026-10-11 `make eval FIX=creami MODEL=haiku`: cost $0.04224845, 11 calls (8 editor, 1 revise, 2
  critic), editor cache_read 16,746 to 74,011 from request 2 on; 2 renders, critic 23/35 (Haiku),
  shipped render 1. `eval/results/2026-10-11/creami-haiku.json`.
- 2026-10-11 `make eval FIX=creami`: cost $0.3443939 (editor $0.2323, critic $0.1121); editor
  cache_read 16,746, 20,751, 34,012, 46,061, revise 49,964; critic 23/35 twice, not passed;
  outputs `out/eval/2026-10-11/creami-sonnet-064755/{text,clean}.mp4`.
  `eval/results/2026-10-11/creami-sonnet.json`.
- 2026-10-11 Sonnet improvement rounds (`make eval FIX=creami`): round 1 $0.3221477 (24, 24),
  round 2 $0.3424261 (21, 21), round 3 $0.4218734 (22, 23); none passed; cache reads on every
  editor request from the 2nd in each. Files `eval/results/2026-10-11/creami-sonnet-174555.json`,
  `-175149.json` and `creami-sonnet.json` (round 3). Branch total $1.4731.
- Unbilled refusals on the way ($0 each, records kept): key not workspace-scoped (10 Oct),
  untyped `music` schema, strict grammar too large (11 Oct).
- 2026-10-10 STEP-02 local gate on cf1def3: `GATE step02 PASS`. Render roundtrip: text.mp4 and clean.mp4 1080x1920, h264, 30/1, aac, 10.802042 s, I: -13.9 LUFS each; input folder 6 files SHA-256 equal (D02); qa.json 6 hard checks true.
- 2026-10-10 CI run 38029390044 on #2: `make ci` passed in 5m56s on ubuntu-24.04; 245 passed, 1 skipped (case-variant guard test: Linux is case-sensitive).
- 2026-10-10 Editor image (CI, linux/amd64): built in 29 s, 1,264,698,610 bytes; `reel render` inside it on the fixtures exits 0 with every hard check true (tests/integration/editor/test_image.py).

## Log

### 2026-10-10 — STEP-03 build: `reel make` with Claude, `make eval`

Before: the WIP of the plan below, parked on a branch stacked on `step-02-pipeline`, with `prompt.py`
and the Claude adapter missing. After: `step-03-editor-loop` rebuilt on origin/main (the 8 WIP
commits cherry-picked; conflicts only in `constants.py` and this file), plus:
- `reel_studio/adapters/claude/client.py`: SDK retries off; our retries for connection errors, 408,
  409, 429, 5xx and mid-stream error events, twice with doubling backoff (`config/anthropic.toml`);
  both 400 spend limits and the tier-cap 429 raise `SpendLimitReached` at once (F13); every attempt
  logged with `latency_ms`. `create` streams (F210). The settings file is `anthropic.toml` because a
  quoted `claude.toml` trips the global model-id hardcode hook.
- `reel_studio/editor/evaluate.py` + `make eval FIX=<name> [MODEL=haiku]`: one run of `make` on
  `REEL_FIXTURES_DIR/<name>`, cost and token counts from the run's `requests.jsonl`, written to
  `eval/results/<date>/<fixture>-<model>.json` in the gate's contract (the unit test checks it with
  the gate's own `eval_problems`). `MODEL=haiku` runs editor and critic on Haiku (plumbing, D32).
  `limits.toml [eval].run_cap_usd = 2.5` lowers the order cap for a run, so two runs fit the $5.
  A failed run still writes what it spent; an earlier same-day file is renamed, never overwritten.
- Senior review of the whole branch: FAIL (3 critical, 11 warnings); fixed with tests: C2 (the
  32,000-token retry could never be sent: the SDK refuses non-streaming requests that may exceed ten
  minutes), C3 (the tier cap was read from the wrong field; fixtures now verbatim from the docs), W1-W5,
  W7, W9, W11, S1. Left open: C1 → Needs Kevin 20; W6 (a revise request more than 5 minutes after the
  last editor call reads no cache; the gate wants cache reads on every request from the 2nd: the
  1-hour TTL costs 2x input to write and has no price row yet); W8 (`--voice on` with a Gemini key keeps
  the voice with no transcript until STEP-05); S2-S7.
- Not done: a paid `count_tokens` test for the 512-token cache minimum (F07). Unit tests cannot read
  the key (conftest isolation); the paid run's `cache_read_input_tokens > 0` proves the same thing.

Paid runs: see Evidence lines.

### 2026-10-10 — STEP-03 plan (written on the parked branch; files as built: `make.py`, `evaluate.py`)

TONIGHT.md: build test-first with a fake model client; stop before the first paid run. The two paid
runs (`make eval FIX=creami MODEL=haiku`, then Sonnet) wait for Kevin; budget ≤ $5.

SDK facts (Context7 /anthropics/anthropic-sdk-python, 10 Oct 2026, anthropic 1.13.0): top-level
`cache_control={"type": "ephemeral"}` on `messages.create`; `output_config={"effort": ...}`
(low/medium/high/xhigh/max); `messages.count_tokens(**params)`; usage `input_tokens`, `output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`; `APIStatusError.status_code/.type/.request_id`;
the SDK's default retry set (408, 409, 429, 5xx, connection) is the one our wrapper owns with
`max_retries=0`. The SDK's HTTP layer is `httpx2`, so tests never build SDK errors: a pure classifier
decides retry / SpendLimitReached / ProviderUnavailable from (status, type, message).

Build order, each module test-first:
1. `editor/meter.py` (task 4): prices from `config/prices.toml`, Haiku long tier, worst-case guard,
   exact cost (Decimal). First test: baseline usage costs exactly $0.164 + $0.325.
2. `tests/fakes/claude.py` + `adapters/claude/client.py` (task 1, 5): scripted fake recording requests;
   real adapter = SDK call + classifier + JSON log line. First test: classifier table.
3. `editor/tools.py` (task 3): Pydantic inputs → strict schemas without numeric bounds; handlers over
   STEP-02's sheets/strip/grade_preview/edl; images ≤ 2000 px. First test: 13th `read_strip` refused.
4. `editor/loop.py` (task 5): the §3 loop. First test: identical tools/system/tool_choice every request.
5. `editor/critic.py` (task 6): `submit_review` tool, gates from limits.toml. First test: fail twice →
   higher total shipped with the weakness named.
6. `editor/prompts/` (task 2): kit SKILL.md, references, critic prompt, styles, structures, brief.
   First test: byte-equal system prompt across two builds, > 4,000 characters.
7. `editor/run.py` + `reel make` (tasks 7, 9): prepare → loop → render → qa → critic. First test: no
   Gemini key forces voice off with the notice.
8. `make eval` target + `eval/run.py` (task 8): written and unit-tested with the fake; never run tonight.

### 2026-10-10 Review fixes, engine items 1-5 (`~/projects/reel/REVIEW-FIXES.md`, step-02-pipeline)
Before: one odd photo (10 x 4300) or a width-0 probe aborted the order (MemoryError,
ZeroDivisionError); style photos decoded at any size; natural_db -6 gave -19.9 LUFS; one CLI test
could not fail. After: each bad file is skipped with a `SKIPPED` or `style photo ... skipped` log
line; `media.toml [prepare].max_pixels` = Pillow's limit (F209) caps cover sizes and style photos;
loudness lands within 1 LU of -14 at natural_db -6; the read-only test reaches the read (checked
against a mutant). Each item has its failing test first and its own commit. LESSONS L13-L15.
Senior review: PASS on c422eea; its two warnings (cap wiring at both call sites, the
DecompressionBombError branch, all unpinned) closed by da8873d, PASS again (diff 7173369..da8873d,
sha256 2b3a8c31...). `make ci` green on da8873d (257 passed, 1 skipped).
Follow-ups: Needs Kevin 16 (natural_db has no audible effect now). Same root cause, out of scope:
a photo the process cannot read raises PermissionError while staging (`prepare.py`, the copy into
originals/), which is not a MediaError, so it aborts the order (reproduced by the reviewer).
`test_edl_json_is_read_not_written` would still pass if a new exit 2 appeared before the read;
asserting the precheck message would close that.

### 2026-10-10 — STEP-02 phase B: the media package, `reel render`, the editor image

Before: config and plan only. After: `reel_studio/editor/media/` (20 modules, each under 300 lines;
`core/media_config.py`, a 400-line list of config fields, is the one file over), `reel render`,
synthetic fixtures, `docker/editor.Dockerfile`, CI's zscale check, FACTS F200-F206. One commit per
module. Each module's test was written and run before the module existed and failed at import or
collection; those runs are in this session's transcript, not in the commits (the review rightly
found no failing run recorded in history).

Kit behaviour kept (D46; ffmpeg arguments byte-identical and grade maths within 2.7e-6, measured by
the review against transcribed kit functions) except: D38 sheets (new code); the 5e-3 identity
tolerance; review sheets capped at F08's 2000 px (the critic reads them); originals staged one at a
time; unknown EDL fields, blank labels and positions other than top/center/low are errors; `null`
audio, defaults or versions are rejected; zero speed is an error instead of a crash; a v1 EDL must
list every unused clip in `dropped`; a QA run that measures no loudness fails instead of passing;
a decompression-bomb photo is skipped like any unreadable file; render intermediates live in a system
temp folder; `--out` inside the input folder is refused (D02).

Phase B review (FAIL: 2 critical, 12 warnings) and what changed: C1 image test could not pass in CI →
fixed (06caee0); C2 `--out` inside the input folder overwrote a user file → refused, tested
(7665d1c); W1-W5, W9, W11, W12, S1, S3-S6 fixed with tests (7665d1c, c31d62f, 06caee0); W6 gaps
partly pinned by new tests; W7 → Needs Kevin 14; W8 → Needs Kevin 13; W10 → F206; S2 (outputs not
atomic), S7 (codec names inline), S8 (small drifts) left as follow-ups. Re-review: PASS, plus W-A
(`--out` guard missed `out/work` and case-variant paths), W-B (its test was vacuous after precheck) and
W-C (a wrong FFPROBE_PATH read as no usable input), fixed in e10484c. Round 3 (PASS) found the W-C
test vacuous and the guard one-directional (an input folder inside `out/work` was rewritten): both
fixed in the next commit, the tool tests proved by deleting `ffmpeg.check()` (both then fail). Still
unpinned by tests: dead-air and blur warnings, the hook `""` rule, the size and black-frame hard
checks failing (review S-A).

Port map as built (plan B rows → modules): tools.py (common.py), prepare.py, colour.py + measure.py
(prep.py measure, grade.py stats), sheets.py (new, D38), strip.py, grade.py, textcards.py,
edl_models.py + edl.py (render.py --check), render.py + render_filters.py + render_steps.py,
qa.py + qa_frames.py + qa_sheets.py, shots.py + pipeline.py (prep.py main), fonts.py, cli/reel.py.

Routine choices made without asking: unknown EDL fields are errors, not ignored; `title` still reads as
`hook_text`; caption and music-hint limits live in `media.toml [edl]` (EDITOR §7); every ffmpeg call
has a 1800 s timeout (`media.toml [tools]`, not a kit value); `--out` defaults beside the input
folder; fixture files get fixed file times so clip ids never depend on encode speed; `media.toml`
loads through its own `config.load_media()`, so main's `Config` shape is unchanged.

Follow-ups: Needs Kevin 10-14; image size and build time from CI; review S2/S7/S8; `reel make` (STEP-03) reuses
`pipeline.build_shots`, `edl.validate`, `render.render` and `qa.run` unchanged.

### 2026-10-09 — STEP-02 phase A: inventory and port plan (no package code)

Before: no `config/media.toml`, no plan. After: `config/media.toml` (249 kit values, each with unit
and `file.py:line`), this plan. The old kit was only read; proof at the end.

#### A. Kit inventory (`$OLD_KIT_DIR/scripts/`, 10 files, 1,751 lines)

| Kit file | Functions | ffmpeg / external calls | Constants (where they go) |
|---|---|---|---|
| `common.py` (173) | `slug`, `KitError`, `log`, `_brew_tool`, `find_tool`, `ffmpeg`, `ffprobe`, `has_filter`, `run`, `probe`, `is_hdr`, `font_path`, `main_guard` | `ffmpeg -hide_banner -filters` (:93); `ffprobe -v error -print_format json -show_streams -show_format` (:107) | `OUT_W/H/FPS` 1080/1920/30 (:19) and `SAFE` 65/1015/270/1250 (:24) → `constants.py` (D43, Meta safe zone); `VIDEO_EXT`, `IMAGE_EXT`, `SKIP_NAMES` (:26-29) → `constants.py`; HDR transfers `arib-std-b67`, `smpte2084` (:151) → `constants.py`; stderr tail 15 (:101), probe error 300 chars (:111) → `[tools]`; Homebrew paths, `REEL_FFMPEG` env (:49, :62) → `settings.py` `ffmpeg_path`, `ffprobe_path` with no default: the image (D72) has Debian ffmpeg on `PATH`, the Mac sets the Homebrew `ffmpeg-full` path in `.env`; the Homebrew lookup is not ported |
| `prep.py` (306) | `tonemap_chain`, `sort_key`, `cover_size`, `make_proxy`, `photo_proxy`, `detect_cuts`, `split_windows`, `frame_at`, `colourfulness`, `measure`, `build_sheets`, `main` | proxy: `-vf [tonemap],scale=W:H:flags=lanczos,fps=N,format=yuv420p,setsar=1 -c:v libx264 -crf 17 -preset veryfast -g fps -color_* bt709 -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest -movflags +faststart`, plus `-f lavfi anullsrc=r=48000:cl=stereo` when silent (:78-85); tonemap `zscale=tin=…:pin=bt2020:min=bt2020nc:t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p` (:46-47); photo `-loop 1 -framerate 30 -t 3` + `zoompan=z='1+0.06*on/N'…` (:106-112); PySceneDetect `detect(AdaptiveDetector(min_scene_len="0.6s"))` (:121); OpenCV seeks (:132) | `[prepare]`, `[prepare.tonemap]`, `[prepare.photo]`, `[measure]`; `ROW_H`, `SHEET_W/H` (:32-33) dropped with `build_sheets` (Needs Kevin 2); Hasler-Süsstrunk 0.3 (:141) → `constants.py` (formula) |
| `grade.py` (277) | `frame_stats`, `merge`, `reference_stats`, `_lab`, `_rgb`, `correction_params`, `apply_transform`, `write_cube`, `set_stats_of`, `grade_config`, `build_luts`, `hero_frames`, `main` (preview sheet) | none (writes `.cube` files read by `lut3d`) | `[grade]`, `[grade.stats]`, `[grade.match]`, `[grade.look_common]`, `[grade.looks.*]`, `[grade.preview]`; `LOOKS` (:31) → EDL enum |
| `render.py` (380) | `seg_get`, `seg_dur`, `validate`, `crop_filter`, `grade_filter`, `atempo_chain`, `text_events`, `render_segment`, `measure_loudness`, `finalize`, `main` | segment (:239-245): `-ss in -t len -i proxy` + crop/blur chain, `lut3d=…:interp=tetrahedral`, `eq`, `setpts`, `fps=30`; audio `asetpts,atempo…,volume,aresample=48000,apad,atrim,afade` → `libx264 -crf 12 -preset superfast`, `pcm_s16le` `.mkv`; loudness pass 1 (:252-257) `concat … loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null`; final (:271-303) concat + PNG `overlay enable=between(t,…)`, loudnorm `linear=true` pass 2 or `volume,aresample=192000,alimiter=limit=0.8:attack=1:release=50:level=false,aresample=48000`, `libx264 -preset medium -crf 18 -profile:v high -r 30 -g 60 -maxrate 20M -bufsize 40M`, `aac -b:a 128k -ar 48000 -ac 2 -movflags +faststart` | `[edl]`, `[edl.format_target_s]`, `[edl.defaults]`, `[render.*]`; `ROLES`, `LONG_OK` (:30-32) and the role sets at :135, :150 → EDL enums; -14 LUFS (:257, :287) → `constants.py` (D42); `FORMATS` short-cut ranges (:33-37, second tuple) unused in the kit, not ported |
| `qa.py` (244) | `grab`, `ssim`, `stats`, `measure_audio`, `tile`, `grid`, `qa_version`, `main` | `ebur128=peak=true`; `blackdetect=d=0.2:pix_th=0.08,freezedetect=n=0.003:d=1.0` `-f null` (:67-69) | `[qa]`, `[qa.sampling]`, `[qa.sheets]`; SSIM c1/c2 0.01/0.03 (:45) → `constants.py` (Wang et al. 2004) |
| `textcards.py` (88) | `_wrap`, `render_card` | none (Pillow) | `[text]`; `STYLES` (:17), positions (:57-64) → EDL enums |
| `strip.py` (73) | `main` (filmstrip) | none (OpenCV, Pillow) | `[strip]`; 2000 px (:67) → `limits.toml [sheets].max_image_side_px` (F08) |
| `shots.py` (40) | `main` (prints the clip/window table) | none | none |
| `selftest.py` (97) | `make_inputs`, `edl_for`, `main` | HDR: `testsrc2=s=1920x1080:r=30:d=4` + `sine=f=440:d=4`, `zscale=…t=arib-std-b67:p=bt2020:m=bt2020nc,format=yuv420p10le`, `libx265 -tag:v hvc1`, colour tags, then `-display_rotation:v:0 90 -c copy` (:30-37); 60 fps `testsrc2=s=1080x1920:r=60` + `sine=f=660`, 5 s (:41-42); landscape `1920x1080:r=30`, 4 s, no audio (:43-44); long take `testsrc` 6 s + `smptehdbars` 8 s concat + `sine=f=330:d=14` (:45-48); photo 1200×1600 (:49); style photo `_VSCO.jpg` (:50) | fixture parameters stay in `tests/fixtures/make_clips.py` (tests are not product config) |
| `status.py` (73) | `media`, `state`, `main` | `has_filter` | `STALE_DAYS` 180 (:19); not ported (kit folder states; the product has orders) |

Kit dependencies (`requirements.txt`, pinned 7 Oct 2026): `scenedetect==0.7.1`, `opencv-python==5.0.0.93`,
`numpy==2.5.3`, `pillow==12.3.0`, `pillow-heif==1.8.0` (`claude-agent-sdk` is not ported, D30).
Phase B adds them to the `editor` extra with one HANDOFF line each; `opencv-python-headless` instead
of `opencv-python` for the slim image (no libGL), to confirm from the PyPI page before adding.

#### B. Module map → `reel_studio/editor/media/`, and the first failing test of each

Order is the build order. `unit` = `tests/unit/editor/` (no ffmpeg, fakes only); `integ` =
`tests/integration/editor/` (real ffmpeg on the session fixtures). Each module also gets the
empty / one / many / failure cases (craft rules); only the first test is listed.

| # | New module | From kit | First failing test (written and seen failing before code) |
|---|---|---|---|
| 0 | `tests/fixtures/make_clips.py` + session fixture | `selftest.py:25-51` | integ `test_fixtures_have_expected_streams`: five clips + one photo; HDR clip probes `arib-std-b67`, rotation 90; 60 fps clip; landscape without audio; long take 90 s (STEP-02, the kit's is 14 s) with a hard cut; JPEG still |
| 1 | `tools.py` (ffmpeg port adapter: `run`, `probe`, `has_filter`, `is_hdr`) | `common.py:56-151` | integ `test_probe_swaps_size_for_rotated_clip`: the HDR fixture probes as 1080×1920 portrait. unit `test_run_error_keeps_last_15_stderr_lines` with the fake runner. Raises `RenderError`/`NoUsableInput` (EDITOR §10) instead of `KitError`; no `print`, JSON log per call with `latency_ms` (D74) |
| 2 | `prepare.py` (`cover_size`, `make_proxy`, `photo_proxy`, `tonemap_chain`, `sort_key`, discovery) | `prep.py:37-115, 225-275` | integ `test_hdr_proxy_is_sdr_bt709_cover_1080x1920`: proxy `color_transfer=bt709`, `pix_fmt=yuv420p`, covers 1080×1920. Then: 60 fps → 60, 30 → 30; silent clip gains a stereo track; photo → 3 s clip with audio; the work-folder copy of the original is gone once its proxy exists, one file at a time (new: the kit reads inputs in place); luma check (Needs Kevin 1) |
| 3 | `measure.py` (`detect_cuts`, `split_windows`, `frame_at`, `colourfulness`, `measure`, clip colour stats) | `prep.py:119-163, 276-290` | unit `test_split_windows_caps_at_24_and_covers_range`; integ `test_long_take_cut_detected` (cut at the fixture's join ± 0.1 s) |
| 4 | `sheets.py` (new, D38) | replaces `prep.py:167-221` | unit `test_sheet_is_1536x864_with_16_tiles` on synthetic numpy frames; then 2-6 frames per clip, legend tile → (clip, t), near-duplicates dropped |
| 5 | `strip.py` | `strip.py:24-69` | integ `test_strip_of_long_take_fits_2000px` (90 s range, 30 frames, both sides ≤ `max_image_side_px`, F08); end clamped to duration |
| 6 | `grade.py` (stats, match, looks, `.cube`, preview) | `grade.py:37-271` | unit `test_strength_0_match_0_is_identity` (`apply_transform` returns its input within 5e-3: the float32 RGB→Lab→RGB round trip alone deviates 3.41e-3, measured on the kit by the reviewer); `test_cube_has_33_cubed_rows_red_fastest`; preview ≤ 2000 px (F08) |
| 7 | `textcards.py` | `textcards.py:21-88` | unit `test_long_label_shrinks_inside_safe_zone` (42-char label: ≤ 3 lines, `inside_safe_zone` true) |
| 8 | `edl.py` (Pydantic v2 models + `check(edl, shots) -> Report`) | `render.py:42-163`, `edl-schema.md` | unit `test_check_returns_every_violation`: an EDL with three independent errors yields three errors, not one. Then `audio.music` refused, v1 fields, warnings kept separate from errors |
| 9 | `render.py` (`crop_filter`, `grade_filter`, `atempo_chain`, `text_events`, `render_segment`, `measure_loudness`, `finalize`, `render_both`) | `render.py:167-376` | unit `test_atempo_chain_8x_is_three_stages` (`atempo=2.0,atempo=2.0,atempo=2.0000`); integ `test_render_basic_outputs_text_and_clean` (both 1080×1920, 30/1, h264, aac, −14 ± 1 LUFS); refuses `audio.music` before any ffmpeg call |
| 10 | `qa.py` (hard checks + hook/cuts/overview sheets + `qa.json`) | `qa.py:37-226` | integ `test_qa_hard_checks_all_true_on_basic_render`; unit `test_hard_check_values_are_bools`. `hard_checks` keys = the kit's PASS/FAIL lines: `spec_text`, `spec_clean`, `size_duration_text`, `size_duration_clean`, `no_black_frames`, `text_in_safe_zone`. The kit emits one safe-zone line per text box (`qa.py:200-201`); here `text_in_safe_zone` = every box inside, true when there is no text. Loudness stays PASS-or-FLAG as in the kit (`qa.py:113-115`), not a hard check: the gate enforces −14 ± 1 LUFS itself (`scripts/gates/step02.py`). The rest stay flags |
| 11 | `shots.py` (`format_table(shots) -> str`) | `shots.py:18-36` | unit `test_table_lists_every_clip_and_window` (feeds STEP-03's tool result) |
| 12 | `reel_studio/cli/reel.py` `reel render --edl <file> <folder> [--out]` | `render.py:306-376`, `qa.py:229-240` | integ `test_input_folder_byte_identical_after_render` (D02: sha256 of every input file before and after); outputs `text.mp4`, `clean.mp4`, `qa.json` in `--out` |
| 13 | `docker/editor.Dockerfile`, `make image-editor` | — | `slow` test: `reel render` inside the image on the fixtures (CI) |

Every value comes from `config/media.toml`, `config/limits.toml` or `reel_studio/core/constants.py`
(loaded once, validated at start-up). Phase B adds to `constants.py`, each with its source comment:
`OUT_W, OUT_H, OUT_FPS` (D43), `TARGET_LUFS = -14` (D42), `AUDIO_RATE_HZ = 48000`, `AUDIO_CHANNELS = 2`,
`SAFE_ZONE` (`common.py:21-24`), `VIDEO_EXT`, `IMAGE_EXT`, `SKIP_NAMES`, `HDR_TRANSFERS`, the
Hasler-Süsstrunk 0.3 and SSIM c1/c2 coefficients, the `.cube` header lines (`grade.py:172`).
Each ffmpeg filter and option used gets a `docs/FACTS.md` row from ffmpeg-filters documentation.

#### C. EDL schema (`edl.py`): kit fields unchanged (D46) + v1 fields (EDITOR §7)

Kit top level (`edl-schema.md:32-43`, `render.py:51-77`):

| Field | Type | Default | Rule |
|---|---|---|---|
| `format` | enum: recipe, dessert, restaurant, product, compilation, asmr, pov, what-i-eat, food-fitness, other | other | error if unknown; length outside `[edl.format_target_s]` → warning |
| `text_style` | enum: outline, box, plain | outline | error if unknown |
| `defaults` | `{rotate, zoom, focus_x, focus_y, fit}` | — | segment value wins (`render.py:42-43`) |
| `grade` | `{look, strength, match, brightness?, contrast?, saturation?}` | natural, 0.6, 0.6 | look ∈ natural/warm/moody/fresh/clean/reference; strength, match 0..1; fine-tune −0.2..0.2, 0.7..1.4, 0.7..1.5 |
| `audio` | `{natural_db}`; `music` forbidden | natural_db 0 | `audio.music` present → error (D02, D42) |
| `versions` | list of Version | — | exactly 1; names unique, `[A-Za-z0-9]+` |

Version (`edl-schema.md:45-49`): `name`; `hook_text` (alias `title`, `render.py:152`); `title_seconds`
(2.5); `title_position` (top/center/low, default top); `segments` (non-empty). Warnings: first role
not hook, hook > 3.5 s, hook > 7 words, > 9 labels, last role not payoff/verdict/reveal, jump-cut risk.

Segment (`edl-schema.md:51-62`): `clip` (known id), `in`, `out` (`0 ≤ in < out ≤ duration + 0.01`),
`speed` (1.0; 0.25-8; < 0.8 only on ≥ 50 fps), `role` (15-value enum, default other), `text` (≤ 42),
`text_span` (1), `text_position` (top/center/low), `focus_x`, `focus_y` (0..1), `zoom` (1.0-2.0),
`rotate` (0/180), `fit` (crop/blur), `audio_db` (0), `mute` (false), `allow_long` (false), `note`.
Errors: on-screen < 0.25 s; non-hook/reveal/payoff/verdict/reaction > 2.0 s without `allow_long`;
total outside 3-90 s. Warnings: nearly static, blurry (from measured windows).

v1 additions (EDITOR §7):

| Field | Type | Rule |
|---|---|---|
| `style` | enum from `config/styles.toml` keys: montage, recipe, long_take, talking, tutorial | must equal the order's style (checked when an order is given; `reel render` passes none) |
| `dropped` | list of `{clip, reason}` | `clip` known; every input not in a segment appears once |
| `preferences` | list of `{text, applied: bool, why}` | one per chip and note sentence (checked in STEP-03 where the order exists) |
| `caption` | string | ≤ 2,200 chars |
| `music_hint` | string | ≤ 120 chars |
| `assumptions` | list of strings | — |
| `check_by_eye` | list of strings | — |
| Segment `beat` | string | purpose in the story |
| Segment `quote` | string | speech only: exact words kept |
| Segment `visual_check` | bool | speech only |

Open for phase B: whether the v1 fields are required in hand-written EDLs. Proposal: optional in the
model, required by the loop's `write_edl` check (STEP-03), so `tests/fixtures/edl/basic.json` can stay
close to the kit's selftest EDL (`selftest.py:54-71`). Length limits go to a new `config/limits.toml`
`[edl]` table, `caption_max_chars = 2200` and `music_hint_max_chars = 120`, citing EDITOR §7, not into code.

Validation design: Pydantic collects every field error in one `ValidationError`; the cross-field and
shots-dependent rules run in `check(edl, shots)`, which appends to a list instead of returning at the
first problem, and returns `Report(errors, warnings)` (the kit mixed `continue` after some errors,
`render.py:95, 99, 103`; those skips stay, since later rules need valid in/out/speed).

#### D. Evidence

- `config/media.toml` parses (tomllib: 10 tables). A checker matched each value against its cited
  kit line: 249 values checked, 1 manual (`center_offset_px = -100`, kit writes `- 100` at
  `textcards.py:60`).
- Old kit unchanged: file list, sizes, mtimes and sha256 (files < 50 MB) snapshotted before reading
  and compared after writing: identical (2,651 files; `.env*` skipped by rule, never read).
