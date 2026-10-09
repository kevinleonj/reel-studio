# Handoff — lane web

Written by the web lane only. Newest entry on top.

## Status board
- Done: task 1 (Orders, Storage, Mailer, Launcher ports with fakes; contract suites green on the fakes and on the real Firestore emulator and Mailpit), task 2 (every §7 route without payments, tests per route and error code), task 3 (web app), task 4 (fake editor), task 5 backend-free (128 Playwright tests, phone + laptop, axe), `web/` wired into `make ci` (ci-web) and `make prerelease` (Playwright + Lighthouse budget).
- Partly: task 5's real-stack happy path (needs `make up`).
- Blocked: task 6 (`compose.yaml`, `docker/api.Dockerfile`, `make up`/`make down`) and the API's composition root wait on the `WebSettings` fields below (`reel_studio/settings.py` is outside this lane).
- Not started: task 8 (Kevin does it, TONIGHT.md).
- Next: Kevin adds the settings fields → composition root `reel_studio/api/main.py` + dispatcher entry point, compose, Dockerfile, `make up`, live gate checks.

## Needs Kevin
- **`WebSettings` fields (blocks task 6).** The laptop API and dispatcher need these deployment values; `reel_studio/settings.py` is the main lane's file, so I did not touch it. Proposed, all without defaults unless marked:
  - `firestore_project: str` (the emulator's project id, e.g. `reel-studio-local`; `FIRESTORE_EMULATOR_HOST` itself is read by the Google client, F308)
  - `smtp_host: str`, `smtp_port: int` (Mailpit in compose: `mailpit`, `1025`; F309)
  - `data_dir: Path` (the filesystem Storage root, `./data/` mounted at `/data`)
  - `web_dist: Path` (the Astro build the API serves)
  - `voice_available: bool` (D14/D62: the API never holds the Gemini key, so it is told whether this server can transcribe)
  - `dispatcher_poll_seconds: int` is a tunable, so it goes in `config/limits.toml` instead (this lane can add it).
  Also `.env.example` lines for them.
- **New tunables in `config/limits.toml` to review (added 10 Oct 2026):** `[upload] backoff_ms = 1000`; `[web] request_timeout_ms = 15000`, `chunk_timeout_ms = 90000` (one 8 MiB chunk at 1 Mbit/s ≈ 67 s), `signed_url_minutes = 60`, `rating_max = 5`, `comment_max_chars = 1000` (both ARCHITECTURE §7), `google_tag_url` (F70). `core/config.py` models them.
- **New ports beyond ARCHITECTURE §3's list:** `OrderUpkeep` in `core/ports.py` (`mark_viewed`, `set_feedback`, `mark_deleted`, `sweep`, `queue_position`) — kept separate so STEP-01's binding-method test for `Orders` stays as pinned. Please confirm or move them into §3.
- `.claude/doc-ledger.json`: the global doc gate (`~/.claude/hooks/gate-docs.sh`) reads `<session cwd>/.claude/doc-ledger.json`, which is outside every lane and hook-protected. Kevin installed it by hand on 9 Oct 2026. Pending entries for phase B are in `web/doc-ledger.pending.json` (git-ignored). The gate misreads multi-line `import type {` as a library named `type`, and `node:fs`/`node:path` as non-stdlib.
- `npm audit`: 7 high, one root (`braces` ReDoS via `micromatch`/`fast-glob` in the `shadcn` CLI tree, build-time only). Not triaged.
- `scripts/check_literals.py` `WEB_HOMES` still exempts `web/src/lib/analytics.ts`, which no longer holds a URL (the tag URL arrives from `/api/config`); the scanner is protected.
- `public/og.png` is a 1200×630 screenshot of the landing page; replace it with real artwork when there is some.
- Kevin's global hook commits every edit as `chore(auto)`; the branch was rebuilt into logical commits on top of `origin/main` before the push (TONIGHT.md rule).

## Evidence lines (the gates read these)

## Log

### 10 Oct 2026 (night) — STEP-06 phase B: ports, API, fake editor, CI wiring

After STEP-01 merged (`git merge origin/main`, `make setup`). Every unit failing test first.
- **Orders** (`core/order_rules.py` pure transitions shared by `tests/fakes/orders.py` and
  `adapters/orders_firestore.py`; one transaction per transition, reads before writes, bounded attempts,
  one log line with latency per call). Contract suite `tests/contract/test_orders.py`: 13 cases (one
  place per checkout, week fills, expiry gives the place back, idempotent fulfilment, two slots, stages,
  finish frees the slot, failure gives the place back (D22), pause stops launches (D26), viewed once,
  feedback, delete, sweep: dead lease → `job_killed`, missed checkout → expired, 7-day paid →
  abandoned (D25), queue position). Green on the fake and on the Firestore emulator.
- **Storage** (`adapters/storage_local.py`): the filesystem adapter answers uploads with Cloud Storage's
  own resumable protocol (F307) so the browser code is one; HMAC-signed, expiring download links.
  Contract suite on fake + local (8 cases), protocol suite (10 cases).
- **Mailer** (`adapters/mailer_smtp.py`, `templates/email/*`): the five UX §3 emails, autoescaped,
  < 100 KB, no images; SMTP to Mailpit logs template and latency, never address or body. Contract on
  fake + Mailpit.
- **Launcher** (`adapters/launcher_local.py`): `Dispatcher.tick()` sweeps every 60 s, takes slots, launches;
  a failed launch fails the order and frees the slot. `FakeEditor` (task 4) walks the real stage names
  (listening only with voice) and writes fixture outputs + a result in the contract shape.
- **API** (`reel_studio/api/`): `create_app(ApiDeps)` with every §7 route that applies without payments,
  the laptop chunk endpoint and signed downloads, the static site (`/new` and `/o/*` with
  `X-Robots-Tag: noindex, nofollow` and `Referrer-Policy: no-referrer`; `/_astro/*` immutable; HTML
  `no-cache`; built 404). Same 404 for a wrong id, wrong token or no token; token stored as SHA-256;
  rate limits per address (10/min checkout, 120/min order calls); request logs carry the route template,
  never the path, query or token (tested). 65 API tests.
- **Wiring**: `mk/web.mk` — `ci-web` (npm ci, astro check + build, ESLint, policy test) runs in `make ci`;
  `make test-emulator` starts the pinned Firestore emulator + Mailpit and runs the `emulator` tests;
  `make prerelease` runs Playwright and `web/scripts/lighthouse.mjs` (LCP ≤ 2.5 s, CLS ≤ 0.1, TBT ≤ 200 ms
  as the lab stand-in for INP; measured 1.2 s / 0 / 0 on `/` and `/privacy`, 2.1 s / 0 / 0 on `/new`).
  `scripts/ci-install.d/web.sh` installs Playwright's Chromium only with `REEL_PRERELEASE=1`.
- New dependency: `lighthouse` 13.5.0 (dev) — the speed budget STEP-06 asks for; `@lhci/cli` lost (a
  server and config we do not need); Chrome comes from Playwright, so no `chrome-launcher`.
- Second senior review (PASS at a9f7591, four warnings): N1 stale poll after Start, N2 slow-link timeouts,
  N3 empty files, N4 unpinned fixes — all fixed; 38 new e2e cases, N1 and N2 seen red against mutants.

### 9-10 Oct 2026 (night) — senior review of phase A: FAIL, findings fixed

TONIGHT.md web steps 1 and 2 done: Context7 entries for the phase B Python libraries are in
`web/doc-ledger.pending.json` (git-ignored; fastapi, starlette, uvicorn, google-cloud-firestore,
httpx, jinja2, pydantic, pydantic-settings, plus smtplib/email/tomllib, which the gate does not
treat as stdlib); the background wait for STEP-01 is running. Docker 29.3.1 answers.

Review verdict FAIL (1 critical, 15 warnings). Fixed:
- C1 token in Referer: `<meta name="referrer" content="no-referrer">` in the layout; e2e
  `robustness.spec.ts` records every Referer when landing on `?t=` (seen red without the meta: 5 leaks).
  Phase B: the API also sends `Referrer-Policy: no-referrer` on the shells.
- W1 a 308 without progress no longer loops (no-progress counts as a failed try); `chunk_bytes` must be a
  multiple of 256 KiB (`checkSettings`). W2 one upload pool per page shared by every pick and Retry.
  W3 every fetch has `AbortSignal.timeout` (new config `timeouts{request_ms, chunk_ms}`; one 15 s
  bootstrap limit for the first `/api/config`). W4 mock modes for partial persistence, never-advancing
  sessions and in-flight counting (`upload-protocol.spec.ts`).
- W5 a failed `/api/config` is not cached; `paid` and the error state are polled. W6 a failed cancel-refill
  leaves the empty form usable and keeps the link. W7 unknown failure code / status / malformed id / style
  key degrade instead of blanking; both islands sit in an `ErrorBoundary`. W8 `pageshow` resets the
  submit button after Back. W9 Copy falls back to `execCommand` outside a secure context and says when it
  failed; the purchase event's SHA-256 failure is logged. W10 the file listing merges instead of replacing.
- W11 switch is 44 px tall; focus rings at full `ring` (6.3:1); `--input` border 3.28:1; focus moves to
  Delete/back to the opener in the inline confirm; the live region announces one short status line.
- W12 `gtag('set', {page_location: origin + route template})` before any hit; `tag_url`/`ga4_id` validated
  when enabled. W13 the dead ESLint exemption for `analytics.ts` is gone. W14 the pending ledger is untracked.
- W15 `eslint-plugin-react-refresh` removed (its only rule was off). The other ESLint packages
  (`eslint`, `@eslint/js`, `typescript-eslint`, `globals`, `eslint-plugin-react-hooks`) came with the
  `shadcn init -t astro` scaffold's `eslint.config.js`; they are the flat-config base that STEP-06's
  ESLint rules sit on; no alternative considered.
- Also: `pretest:e2e` rebuilds `dist`; the policy test checks the three `no-restricted-syntax` selectors;
  the 404 page sends no `page_view`; FACTS F307 records the Cloud Storage chunk protocol.
- Not done (logged for later): `npm audit` reports 7 high, one root (`braces` ReDoS through
  `micromatch`/`fast-glob` in the `shadcn` CLI tree, build-time only); `tests/e2e` is not type-checked by
  any script; the island bootstrap is inline script, so the API's future CSP needs a hash; a drift check
  between `en.json` chips and `config/styles.toml`; a real-iPhone/WebKit run (task 8, Kevin).
- Stray file: one e2e log was written to `~/projects/reel/e2e.log` (outside the repository) by mistake;
  harmless, left in place because it is outside this lane.

### 9 Oct 2026 — STEP-06 phase A: the web app (session on `step-06-website`, local commits only)

Before: no `web/`. After:
- `web/` scaffolded with `npx shadcn@4.21.4 init -t astro -n web -b radix -p nova` (F302), then every version pinned exactly (no `^`), `package-lock.json` from npm. Node 24.21.0 from the unlinked Homebrew keg: run npm with `PATH=/opt/homebrew/opt/node@24/bin:$PATH` (`.nvmrc`, `engines`).
- Version choices against the latest (F300, F301): ESLint 9.39.5 not 10 (eslint-plugin-react peers ≤ 9); TypeScript 6.0.3 not 7 (typescript-eslint, @astrojs/check peers). No eslint-plugin-astro (needs ESLint 10); `.astro` text is covered by `check_literals.py`.
- Dependencies added beyond the scaffold, one line each: `@astrojs/sitemap` (the `/sitemap-index.xml` that ARCHITECTURE §7 names; hand-writing it lost); `eslint-plugin-react` (STEP-06 names it and its `react/jsx-no-literals` rule); `@playwright/test` + `@axe-core/playwright` (the spec's e2e and axe). Removed from the scaffold: prettier and its two plugins (not in the stack), the template README. No query library: polling is one `usePolling` hook (`src/lib/poll.ts`); TanStack Query lost as a dependency for one GET.
- Pages: `/` and `/privacy` finished HTML (no island); `/new` and `/o/index` static shells with one `client:only="react"` island and `<meta name="robots" content="noindex, nofollow">`; `404.astro`; `robots.txt.ts` (allow all + sitemap from `SITE_URL`); sitemap lists `/` and `/privacy` only. `SITE_URL` is read in `astro.config.mjs` with Vite `loadEnv` from the repo `.env` or the environment, and the build stops without it (F303).
- Every word of UX §2 and the EDITOR §10 failure messages are in `web/src/copy/en.json`; colours and sizes only in `web/src/styles/tokens.css` (one paprika accent, light/dark from the system, 44 px targets as `--spacing-target`). shadcn components were edited to drop arbitrary values (`aria-checked:`/`aria-pressed:` instead of `data-[state=…]`, F306).
- Lint (D76): `eslint.config.js` sets `no-magic-numbers`, `react/jsx-no-literals` (`noStrings`, `ignoreProps`) and `no-restricted-syntax` (URL strings, hex colours, literal `aria-label|placeholder|alt|title|label`) to `error` on `src/**/*.{ts,tsx}`; `web/tests/eslint-policy.test.mjs` (`npm test`) fails unless all three resolve to `error`. Seen red first ("no-magic-numbers must be "error", got undefined"), then green.
- Analytics seam (D75): `src/lib/analytics.ts`, `track(event, params)` with the UX §5 events typed; no-op while `analytics.enabled` is false; consent defaults (four types denied) first; tag script only after `grantConsent()`. The tag URL comes from `/api/config` as `analytics.tag_url` (keeps every Google host out of web code; the global hardcode gate has no allowlist for the URL). Called at every UX §5 event.
- Uploads: `src/lib/upload.ts`, Cloud Storage resumable protocol (`Content-Range`, `bytes */size` offset query, 308 + `Range`), retries with exponential backoff, two files at a time, sizes and counts from `/api/config`. Polling every `poll_seconds` and on `visibilitychange`.
- e2e (`tests/e2e/`, config `web/playwright.config.ts`, run with `npm run test:e2e` in `web/`): UX §6 items 2 (dropped chunk resumes from the server offset), 3, 4, 5, 6, 7, 1 (happy path with the API mocked), 8 (axe: no serious/critical in every state), analytics off (no request to any Google host), SEO/robots/sitemap. Every `/api` call is mocked with `page.route`; `/o/<id>` is mapped to the built shell as the API will do. Honest note: the upload spec was written after `upload.ts`, not before it; it was run and passed on the first real run, so it was never seen red.
- The order page `/o/<id>` shows every status from UX §2. "Start again" links to `/new` without refilling (refilling a failed order needs an API call that §7 does not have yet).

### The API contract this phase defines (phase B must match `web/src/lib/types.ts`)
- `GET /api/config` → `payments`, `voice_available`, `styles[{key, voice_default}]`, `chips{items, exclusive}`, `lengths_s`, `default_length_s`, `text_languages` (codes), `note_max_chars`, `limits{max_files, max_total_bytes, max_file_minutes, allowed_types}`, `upload{chunk_bytes, parallel_files, chunk_retries, backoff_ms}`, `timeouts{request_ms, chunk_ms}`, `poll_seconds`, `feedback{rating_max, comment_max_chars}`, `price{value, currency}|null`, `analytics{enabled, ga4_id, ads_id, tag_url}`. Implemented in `reel_studio/api/routes_public.py` (phase B); the new config keys are under Needs Kevin.
- `POST /api/checkout {settings, code, email}` → `{checkout_url}` (stripe) or `{order_url: "/o/<id>#t=<token>"}` (PAYMENTS=off); errors `{"error": "<code>"}`.
- `GET /api/orders/{id}` (header `X-Order-Token`) → `status`, `settings`, `email_hint` (masked by the API), `queue_position`, `stage{name, elapsed_s}`, `stages_done[]`, `result{versions[{kind, play_url, download_url}], duration_s, caption, text_lines[{at_s, text}], music{mood, tempo}, left_out[{file, reason}], wishes[{wish, applied, reason}], doubts[]}`, `error{code}` (snake_case EDITOR §10 codes, e.g. `cost_cap`, `job_killed`), `feedback_sent`. 404 for a wrong id or token.
- `POST …/uploads {files[{name,size,type}]}` → `{targets[{name, upload_url}]}` in request order; `bad_type` answers `{"error":"bad_type","file":"<name>"}`. `GET …/files` → `{files[{name,size}]}`.

### Waits for STEP-01 (not touched in this phase: `mk/`, `scripts/ci-install.d/`, `pyproject.toml`, Makefile, `reel_studio/`)
- `mk/web.mk`: `npm ci`, `npm run build`, `npx eslint .` and `npm test` inside `make ci`; `npm run test:e2e` inside `make prerelease` with Lighthouse.
- `scripts/ci-install.d/web.sh`: Node 24, `npm ci`, and `npx playwright install chromium` for the prerelease target only.
- Push, `gh pr create`, CI, and `python3 scripts/gates/step06.py` (needs `make ci`, `make prerelease`, `make up`).

### Verification run in this session (9 Oct 2026)
See the session's final message for the pasted output: `npm ci`, `npm run build` (astro check: 0 errors), `npx eslint .` (exit 0), `npm test` (1 pass), `npm run test:e2e` (76 passed, three runs in a row), `check_literals.py` (0 violations).
