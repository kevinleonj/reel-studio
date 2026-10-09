# STEP-03 — The editor loop: `reel make` with Claude

**Outcome:** `uv run reel make ./clips --style montage` produces a Reel edited by Claude Sonnet 5.5 on
the user's own key (Tier 0 works). This is the step that replaces the Agent SDK.

Lane **engine**: the worktree `~/projects/reel/reel-studio-engine` (`git rev-parse --show-toplevel` ends in
`/reel-studio-engine`); do not leave it. Handoff file: `docs/handoff/engine.md`.
Settled: D30–D39, D45, D46, and all of `docs/EDITOR.md` §2–§4, §6–§10. Never add `claude-agent-sdk`
or the tool runner to this package.
Paid budget for this step: ≤ $5, only through `make eval`.

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
grep -o '^ANTHROPIC_API_KEY=' .env
uv run python -c "import anthropic; print(anthropic.__version__)"    # 1.12 or later (F06)
```
Before writing any SDK call, query Context7 `/anthropics/anthropic-sdk-python` for: the top-level
`cache_control` argument, `output_config` (effort), `messages.count_tokens`, `strict` tool
definitions, usage fields, error classes for 400 and 429. Record the answers in FACTS.md.
Branch `step-03-editor-loop`.

## Tasks

1. **Ports and fakes.** `core/ports.py`: `Claude`, `Clock`. `tests/fakes/claude.py`: a scripted fake
   that returns recorded responses and records every request it receives.
2. **Prompts.** Port the kit skill into `editor/prompts/system/editor.md` (tools instead of scripts;
   questions replaced by the defaults in `docs/EDITOR.md` §2), styles `montage.md`, structures
   `showcase.md` and `recipe.md`, the critic prompt, `brief.md.j2`. Test: the system prompt for each
   style is identical across two builds (byte-equal) and above 512 tokens (F07, use `count_tokens`
   in a `paid`-marked test only; offline, assert length > 4,000 characters).
3. **Tools** (`docs/EDITOR.md` §4) generated from Pydantic models; strict; numeric bounds removed from
   the schema and enforced in validators (F11). Tests: each guard returns `is_error` with a message
   that names the valid values; images resized to ≤ 2000 px (F08); `read_strip` refuses the 13th call.
4. **Meter and guard** (`docs/EDITOR.md` §8) reading `config/prices.toml`. Tests: Haiku price tier
   switches above 100,000 input tokens (F05); the guard raises before a call that would cross $5; cost
   uses the higher of the input and cache-write prices for the input part of the worst case (D37); cost
   of the measured baseline usage (1,640,000 cache-read and 130,000 cache-write tokens) computes to
   exactly $0.164 + $0.325 at Sonnet prices (no rounding inside the meter).
5. **The loop** (`docs/EDITOR.md` §3) with the fake client. Tests, written first:
   - tools, system, `tool_choice` and output format are identical in every request of a run;
   - all `tool_result` blocks of one turn go back in one user message, first, matching every
     `tool_use` id (F12);
   - `end_turn` without an edit list gets one nudge, then counts as a turn;
   - `max_tokens`: the cut-off assistant turn is dropped (never sent back) and the request is retried
     once with `max_tokens_retry`; a second cut-off fails with `output_too_long`;
   - `refusal` and unknown stop reasons follow the table;
   - the SDK client has `max_retries=0`; our wrapper retries connection errors, 408, 409, 429 and 5xx
     twice, and never retries a 429 `enforced_spend_limit_reached`;
   - a 400 "You have reached your specified workspace API usage limits" and a 429
     `enforced_spend_limit_reached` raise `SpendLimitReached` with no further call (F13, D45);
   - `requests.jsonl` has one line per call with the fields in §9.
6. **Critic and revise** (`docs/EDITOR.md` §6): gates from `config/limits.toml`; at most 2 renders;
   ship the higher total. Tests with fake critic answers: pass at render 1; fail then pass; fail
   twice → ship the better one with the weakness named.
7. **CLI** `reel make <folder> --style ... --length ... --text-lang ... [--voice off]` writes to
   `./out/<name>/` and prints the result summary and cost.
8. **`make eval FIX=<name> [MODEL=haiku]`** runs `reel make` on `REEL_FIXTURES_DIR/<name>`, prints cost
   and scores, and writes `eval/results/<YYYY-MM-DD>/<fixture>-<model>.json` (committed; model `sonnet` or
   `haiku`): `fixture`, `model`, `cost_usd` (every call, critic included), `critic` {`total`, `passed`},
   `requests` (editor-loop calls only, in order, each with `input_tokens`, `output_tokens`,
   `cache_read_input_tokens`, `cache_creation_input_tokens`), `critic_requests` (same fields),
   `outputs` {`text`, `clean`}. The gate reads this file. **One real run:** `make eval FIX=creami MODEL=haiku` first (about $0.05) to prove the
   plumbing, then `make eval FIX=creami` with Sonnet once.
9. **Without a Gemini key** `reel make` forces voice off and prints the notice (D14). Test it.

## Done when

- `python3 scripts/gates/step03.py` prints `GATE step03 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/engine.md` and the pull request.
- Paid run evidence: cost line, critic scores, both MP4 paths, and `requests.jsonl` showing
  `cache_read_input_tokens > 0` from the second request on.
- Cost ≤ $1.20 and gates passed, or a written reason and a plan in HANDOFF.md.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/engine.md`.)

STOP if: a paid run would exceed this step's $5; cache reads stay at 0 (caching is broken: fix before
any other paid run); the model asks for a tool we do not offer more than twice in a run.
Final message: five-line status board, then the PR link.
