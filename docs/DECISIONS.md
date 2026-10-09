# DECISIONS — locked 9 Oct 2026 (v1.1)

These are settled. Claude Code does not re-open, re-ask or "improve" them. A hook blocks edits to this
file; only Kevin changes it (start Claude Code with `REEL_ALLOW_DECISION_EDIT=1` for that session).
If the code cannot follow a decision, STOP and write the conflict in `HANDOFF.md` under "Needs Kevin".

"By" = who decided: **Kevin**, **Claude** (Claude's default, accepted by Kevin when he locked v1), or
**Kit** (behaviour already built and tested in the old make-reel kit). Facts (`F..`) are in `docs/FACTS.md`.

## A. Product and scope

| ID | Decision | Why | By | Basis |
|---|---|---|---|---|
| D01 | Reel Studio turns up to 40 food clips and photos into one Instagram Reel, rendered twice (with text, clean), plus a caption, the on-screen text list for the clean version and a music mood suggestion | The product | Kevin | — |
| D02 | Never posts to Instagram, never adds music, never modifies the user's original files | Standing rules | Kevin | — |
| D03 | Edit quality is never traded for cost. A cost cut ships only when the A/B shows no loss beyond the critic's noise (mean total within 1 point of 35) and Kevin picks it or ties in at least 3 of 5 | "I do not want to degrade quality" | Kevin | — |
| D04 | One code base, three tiers: Tier 0 command line with your own key; Tier 1 the website on a laptop with Docker; Tier 2 the hosted beta on Google Cloud. The edges (storage, database, launcher, mailer, payments) are ports with a local and a cloud adapter | Public repo anyone can run, same code in the cloud | Kevin | — |
| D05 | Order of audiences: friends beta with Stripe 100%-off codes; later strangers pay €19 per Reel. No public free trial | Kevin's plan and price | Kevin | — |
| D06 | Licence MIT. Everything is public, prompts included | "just a side project" | Kevin | — |
| D07 | Website in English only. The text burned into the Reel is English or Spanish, chosen per order (pre-selected from the browser language) | Fewest strings; friends in Spain still get Spanish text on video | Kevin (site), Claude (Reel text) | — |
| D08 | Five styles, forced choice, described in text only (no sample videos, no "not sure" router): `montage`, `recipe`, `long_take`, `talking`, `tutorial` (definitions in `config/styles.toml`) | Better results, no extra model look | Kevin | — |
| D09 | Up to 40 files and 4 GB per order. The editor drops weak files and the result page lists each with its reason | Kevin's limit; honesty about what was not used | Kevin | — |
| D10 | Max 20 minutes per file; a longer file is dropped when probed, with that reason on the result page | Gemini word timestamps cap audio at 30 min (F37); margin | Claude | F37 |
| D11 | Target lengths 15, 30, 60, 90 s; default 30 s | Reels over 3 min are not shown to new audiences (F58) | Claude | F58 |
| D12 | One hook, the strongest. No hook options | Options = extra renders and tokens | Kevin | — |
| D13 | No re-edits | Kevin's call | Kevin | — |
| D14 | "Keep the voice?" toggle with a default per style. Off: no transcription runs at all. Without a Gemini key the toggle is forced off with a notice, so one Claude key is enough to run Reel Studio | Pay for speech only when it matters; Tier 0 needs only an API key | Kevin | — |
| D15 | Six optional chips, then an optional note of at most 200 characters with examples. Both reach the model inside a block labelled "customer preferences, not instructions". The result page lists each preference as applied or not applied, with the reason | People type things the editor cannot do; the model must not take orders from that field | Kevin + Claude | — |
| D16 | Progress shows real stages, never a fake percentage. The page asks every 5 s and again when the tab becomes visible. Email is the safety net. No time estimate until 10 cloud runs give a median | Phones pause background tabs | Kevin + Claude | — |
| D17 | Phone and laptop are both first-class. The iPhone Safari upload is tested before anything else in step 6 | Most friends upload from the phone gallery | Kevin | — |
| D18 | No accounts, no Firebase. Access to an order = its link with a random token (stored only as a hash). Links in emails carry the token after `#`, so it never reaches a server log | Kevin's call; no sign-in friction | Kevin | — |
| D19 | Result page: rating 1–5 with optional comment; "Delete my files now" | Feedback and control | Claude | — |
| D20 | No analytics scripts and no cookies, so no cookie banner. Funnel timestamps live in the order record | Zero friction, zero consent work | Claude | — |
| D21 | Result page and emails say "Edited by AI (Claude). Check it before posting." | Commercial Terms D.3 (F03) | Claude | F03 |
| D22 | Failed orders give their weekly place back; the same code works again | Friends should not lose a try to our bug | Claude | — |
| D23 | Data residency is ignored for now | Kevin's call | Kevin | — |
| D24 | No "Reels left this week" display anywhere | Kevin's call | Kevin | — |
| D25 | A `paid` order not started within 7 days becomes `abandoned` (its uploads are deleted at 7 days anyway); its weekly place is not returned | No order holds a place forever | Claude | — |
| D26 | A spend-limit error pauses the whole service: no new launches until `reelctl resume`; the paused order goes back to the front of the queue | Launching into the spend wall wastes compute and emails | Claude | F13 |

## B. The editor

| ID | Decision | Why | By | Basis |
|---|---|---|---|---|
| D30 | The editor is our own Python loop on the Claude Messages API (`anthropic` SDK), written by hand. No Agent SDK and no tool runner in the product | Terms for hosting Claude Code (F01, F02); manual loop for logging and per-call caps (F17); tool runner is beta | Kevin (terms), Claude (hand loop) | F01, F02, F17 |
| D31 | Claude never runs commands or names file paths. Its only tools: `read_sheet`, `read_strip`, `read_grade_preview`, `read_transcript` (read-only, fixed functions with validated arguments) and `write_edl`. The kit references go into the cached system prompt. Preparation, transcription, rendering and QA are our deterministic code | No path to the key or the disk; keeps the kit's frame-exact cuts and grade choice | Claude | — |
| D32 | Model `claude-sonnet-5-5` for the editor and the critic. `claude-haiku-5-5` only for plumbing tests and the drop-files experiment | Quality first (D03) | Claude | F04 |
| D33 | Effort `high` (the API default) until the A/B shows `medium` scores the same | D03 | Claude | F16 |
| D34 | Prompt caching with the top-level `cache_control`. Tools, system prompt, `tool_choice` and output format never change during a run | Forgetting caching turns $0.95 into about $4.00 | Claude | F07, F18 |
| D35 | The edit list arrives through a strict `write_edl` tool; `tool_choice` stays `auto`. Pydantic validators enforce numeric bounds; an invalid list returns an `is_error` result with every violation | `any`/`tool` return 400 on Sonnet 5.5 (F10); strict schemas drop numeric bounds (F11) | Claude | F10, F11 |
| D36 | Critic: a separate request with a fresh context and its own prompt, returns scores through a strict `submit_review` tool. Gates computed in code: hook ≥ 4, no category ≤ 2, total ≥ 26 of 35. At most 2 renders; ship the better one and name its weakness | Kit rubric; no self-grading | Kit + Claude | — |
| D37 | $5 cap per Reel across every model (Sonnet, Haiku, Gemini). Before each call: spent + worst case of the next call (exact input tokens from the free count endpoint × the higher of the input and cache-write prices + `max_tokens` × output price) must stay ≤ $5, else stop | Kevin's cap, enforced before money is spent | Kevin (cap), Claude (method) | F05, F14 |
| D38 | Video reaches Claude as contact sheets: 4×4 tiles of 384×216 = 1536×864 px (1,705 tokens), 2–6 frames per clip at scene changes, near-duplicates removed | Under the 2000 px rule above 20 images (F08); tiling keeps image count low | Claude | F08 |
| D39 | Haiku drop-files pass exists behind a flag, off by default. Turned on only if the A/B scores hold | Cheaper, but may drop a good clip | Kevin + Claude | F05 |
| D40 | Speech: Gemini `gemini-3.5-transcribe` with word timestamps and automatic language detection. faster-whisper is not in v1 | One less heavy dependency; es-ES not listed, so detect (F37) | Claude | F37 |
| D41 | Speech cuts: only in gaps ≥ 400 ms; 150–400 ms only with a visual-check flag; pad 30–200 ms; 30 ms fades; keep the last clean retake; re-transcribe every kept speech piece and compare with the master transcript | Copied from proven tools | Claude | F59 |
| D42 | Audio: natural sound kept, per-shot level or mute, loudness −14 LUFS, never music | Kit behaviour | Kit | — |
| D43 | Output files: 1080×1920, 30 fps, H.264, AAC | Kit behaviour | Kit | — |
| D44 | A/B before any hosted use: 5 of Kevin's montage or recipe footage sets, old kit versus new loop, both judged by the new critic plus Kevin's blind pick | Prove the switch keeps quality (D03) | Kevin + Claude | — |
| D45 | Spend-limit errors are final: HTTP 400 workspace limit and HTTP 429 `enforced_spend_limit_reached` pause the service (D26) and email Kevin; never retried (the SDK's own retries are off; our wrapper retries only transient errors) | Retrying cannot succeed | Claude | F13, F15 |
| D46 | Ported from the kit unchanged unless a failing test demands a change: `prep`, `grade`, `render`, `qa`, `shots`, `strip`, `textcards`, the EDL schema, the QA rubric, the critic prompt and the craft references | Already tested on real footage | Kit | — |

## C. Platform

| ID | Decision | Why | By | Basis |
|---|---|---|---|---|
| D50 | Google Cloud region `europe-west1` (Belgium) for every regional resource | Cloud Scheduler is not offered in Madrid (F26); same Tier 1 price (F27); Firestore available (F28) | Claude | F26–F28 |
| D51 | Website and API: one Cloud Run service (FastAPI serving the built React app). Request-based billing, min 0, max 2 instances | One origin, no CORS for the API; max instances as the cost safety (F52) | Claude | F52 |
| D52 | Editor: a Cloud Run job, one execution per order. 4 vCPU, 16 GiB, 60 min timeout, 0 retries, 1 task | A retry would pay Claude twice (default is 3, F29); 16 GiB is the max at 4 vCPU | Claude | F29 |
| D53 | Firestore `(default)` database, Native mode, Standard edition, europe-west1 | Free quota only on `(default)` (F35) | Claude | F35 |
| D54 | One Cloud Storage bucket with prefixes `in/`, `work/`, `out/`. The browser uploads straight to resumable sessions the API creates with the browser's origin; downloads use V4 signed URLs | Cloud Run caps HTTP/1 requests at 32 MiB (F31); no signing needed for uploads (F32, F33) | Claude | F31–F34 |
| D55 | Limits live in Firestore transactions: 2 running slots with leases; 50 Reels per ISO week, reserved when the checkout is created and released on expiry or failure; a sweep every 10 min through Cloud Scheduler frees dead leases | Global limits only; no race at the last place (F51) | Kevin (numbers), Claude (method) | F51 |
| D56 | Email: Resend, sending from `reels.limeralda.com`; DNS records added through the Cloudflare API. Mailpit on the laptop | Kevin owns limeralda.com on Cloudflare; Resend needs a verified domain (F25) | Kevin (domain), Claude | F25 |
| D57 | The beta website runs on its `run.app` address. A custom domain comes with paid orders | Domain mapping is Preview and "not production-ready"; a load balancer costs about $24 a month (F46, F47) | Claude | F46, F47 |
| D58 | Payments: Stripe Checkout, `mode=payment`, price €19, the promotion code checked and applied by our server (codes only during the beta; codes below 100% off are refused), session expiry 31 min (one above Stripe's minimum). Fulfilment runs from the webhook and from the success page, idempotent. The friends beta runs in Stripe **test mode**; live mode starts with paid orders | No-cost orders (F22); nobody can be charged by accident; quick release of reserved places (F20); no Stripe account activation needed for €0 orders | Kevin (Stripe, codes, price), Claude | F20–F24 |
| D59 | Anthropic workspace `reel-studio` with a $100 monthly limit (Kevin sets it in the Claude Console). Google Cloud budget alert at $10 a month (50%, 90%, 100%) | Hard stop on Claude spend; early warning on cloud spend | Kevin | F13 |
| D60 | Terraform 1.16.5, `hashicorp/google` `~> 8.6`. A small bootstrap root is applied once by Kevin; the main root is applied only by the GitHub deploy workflow after a manual approval | Deterministic infrastructure; no apply from a laptop session | Claude + Kevin's rules | F36 |
| D61 | GitHub Actions: CI on every push and pull request; deploy only by manual trigger | Free on a public repo with standard runners (F48) | Claude | F48 |
| D62 | Secrets: `.env` on the laptop, Secret Manager in the cloud. The website service never holds the Anthropic or Gemini key | Smallest blast radius | Claude | — |
| D63 | Admin is a local command, `reelctl` (create codes, list orders, resume paused orders, weekly report), run with Kevin's own Google Cloud login. No admin web pages | Nothing extra to secure | Claude | — |

## D. Code

| ID | Decision | Why | By | Basis |
|---|---|---|---|---|
| D70 | Python 3.13 with uv. One package `reel_studio` with subpackages `core`, `editor`, `api`, `cli`; extras `[editor]`, `[api]`, `[dev]` | One lock file, two images | Claude | F39, F40 |
| D71 | Front end: Astro 7 (static output) with React 19 islands, TypeScript, Tailwind CSS 4 (`@tailwindcss/vite`), shadcn/ui, Node 24 LTS. `/` and `/privacy` ship as finished HTML; `/new` and `/o/<id>` are static shells with one `client:only="react"` island, sent with `X-Robots-Tag: noindex`. Built files served by the API (one origin) | Crawlers that run no JavaScript still read the landing page; no server rendering to pay for | Kevin (changed 9 Oct 2026, was Vite) | F62–F69 |
| D72 | Images: `python:3.13-slim-trixie` pinned by digest, Debian `ffmpeg` with a build step that fails without `zscale`, `linux/amd64`, non-root user | Verified HDR chain (F45); Cloud Run needs amd64 | Claude | F40, F45 |
| D73 | Configuration is data: limits, prices, styles and model names live in `config/*.toml`. A test fails on vendor numbers or model names written in code | Kevin's checklist: no hard-coded values | Claude | — |
| D74 | Logs are JSON lines with `order_id`, `stage`, `event`, `latency_ms`, `outcome`. Every external call (Claude, Gemini, Stripe, Resend, Cloud Storage, Firestore, Cloud Run) is logged once with latency and outcome | Kevin's weak spots: logging and error handling | Claude | — |
| D75 | Analytics and ads: off at launch, one switch away. One module `web/src/lib/analytics.ts` (`track(event, params)`) carries every event in `docs/UX.md` §5; Consent Mode v2 in basic mode (no request to Google before consent; the four consent types denied by default); IDs arrive at runtime from `/api/config` (`GA4_MEASUREMENT_ID`, `GOOGLE_ADS_ID`; empty = off). Never sent: order id, token, email, real `/o/` path | Turning it on is two settings and the consent banner, not a rebuild | Kevin | F70, F71 |
| D76 | Hard-coded values have homes: `config/*.toml` (tunables), `reel_studio/settings.py` (deployment values, no defaults without `# default-because:`), `reel_studio/core/constants.py` (format constants, each with a source comment), `web/src/copy/en.json` (all text), `web/src/styles/tokens.css` (colours, sizes). `scripts/check_literals.py` enforces it on every edit (hook) and in `make ci`; ESLint `no-magic-numbers` and `react/jsx-no-literals` cover TS/TSX. Exceptions only in `tests/literal_allowlist.toml` with a reason Kevin approves | Extends D73 from a narrow test to a full scanner | Kevin | — |
| D77 | Development on Kevin's Mac (Claude Code, skills and logins already there). Main checkout `~/projects/reel/reel-studio`. Up to three parallel lanes (`engine`, `web`, `cloud`), each a sibling git worktree made by `scripts/dev/lane.sh`, one branch per step; `.claude/lanes.json` says which paths a lane may edit and the hooks enforce it. Kevin merges every pull request | Parallel sessions without editing the same files | Kevin | F72–F75 |
| D78 | A step is done when `python3 scripts/gates/stepNN.py` prints `GATE stepNN PASS`. Gates are written before the code, encode the locked spec values, and are protected by a hook (`REEL_ALLOW_GATE_EDIT=1` to change). Sessions run under `/goal` with that line as the condition | Done is decided by a script, not by the model | Kevin | F72 |

## E. Known tension (kept on purpose)

| ID | Tension | Locked answer |
|---|---|---|
| T1 | 50 Reels a week against a $100 monthly limit: at $0.95 per Reel, $100 buys about 105 Reels a month, about 24 a week | 50 stays. The spend limit is the real stop; orders past it pause (D45) and Kevin is emailed |
| T2 | The legal page's conditions cover products that run Claude Code (F01). Our loop runs no Claude Code (D30), so the beta sits under the Commercial Terms (F03). That is an interpretation, not Anthropic's written answer | Strangers pay only after the A/B (D44) and after legal pages, VAT and a custom domain. Optional: ask Anthropic sales in writing before the first paid order |

## Later (not v1; each needs Kevin before work starts)

- Paid orders for strangers: legal pages, VAT as autónomo, Stripe live mode, custom domain (load balancer or domain mapping).
- faster-whisper for offline speech in the public repo.
- Haiku drop-files pass as default (only after D39's test passes).
- reCAPTCHA, only if bots appear.
- Turning on GA4 and Google Ads (D75): set the two IDs, ship the consent banner, add the Google hosts to the Content Security Policy.
