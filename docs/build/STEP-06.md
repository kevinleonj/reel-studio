# STEP-06 — The website on the laptop (Tier 1)

**Outcome:** with only Docker and an API key, someone runs `make up`, opens `http://localhost:8080`
on a laptop or a phone on the same Wi-Fi, uploads clips and gets the Reel on the page and in Mailpit.
Payments are off in this step (`PAYMENTS=off`).

Lane **web**: the worktree `~/projects/reel/reel-studio-web` (`git rev-parse --show-toplevel` ends in
`/reel-studio-web`); do not leave it. Handoff file: `docs/handoff/web.md`.
Settled: D04, D07, D15–D21, D51, D54, D71, all of `docs/UX.md`, `docs/ARCHITECTURE.md` §3, §4, §7.
Paid budget ≤ $3 (one real Reel at the end; every other run uses the fake editor).

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
docker info --format '{{.ServerVersion}}' && node -v
```
Look up with Context7: FastAPI static files and lifespan, the Firestore Python client against the
emulator (`FIRESTORE_EMULATOR_HOST`), Astro 7 static output with `@astrojs/react` islands, Tailwind 4 through
`@tailwindcss/vite`, shadcn/ui for Astro (F62–F66), ESLint flat config with `eslint-plugin-react`, Playwright
device emulation, axe-core for Playwright. Record versions in FACTS.md. Branch `step-06-website`.

## Tasks

1. **Ports and adapters** (`docs/ARCHITECTURE.md` §3) with one contract suite run against the fake and
   the local adapter (cloud adapters are proven by the smoke test in STEP-08, not here): `Storage` (filesystem + chunked PUT endpoint speaking the same resumable protocol:
   `Content-Range`, offset query with `bytes */size`), `Orders` (Firestore emulator), `Launcher`
   (dispatcher process that polls queued orders and runs the editor), `Mailer` (SMTP to Mailpit).
2. **API routes** from `docs/ARCHITECTURE.md` §7 that apply without payments: config, checkout in
   `PAYMENTS=off` mode, order status, uploads batch, files, start, viewed, feedback, delete, sweep
   (dispatcher calls it every 60 s locally). `/api/config` also returns `analytics`
   {`enabled`, `ga4_id`, `ads_id`} from settings (`GA4_MEASUREMENT_ID`, `GOOGLE_ADS_ID`, empty = off). Token hashing, same 404 for wrong id or token, rate
   limits, logs without tokens or query strings. Tests first for each route, including every error
   code.
3. **Web app** (`web/`, D71): `npx shadcn@latest init -t astro`, exact versions pinned in `package.json`
   (no `^`), `package-lock.json` committed. Pages: `src/pages/index.astro` and `privacy.astro` (finished HTML,
   no client JavaScript needed to read them), `new.astro` and `o/index.astro` (static shells, one
   `client:only="react"` island each). The API serves `/o/{order_id}` with `o/index.html` and the headers in
   `docs/ARCHITECTURE.md` §7; robots.txt and sitemap per `docs/UX.md` §2. Every screen and state in
   `docs/UX.md` §2 with the exact words, all of them in `web/src/copy/en.json`; colours and sizes only in
   `web/src/styles/tokens.css`. Uploads two at a time in 8 MiB chunks with resume; polling every 5 s and on
   `visibilitychange`; stage list; result page; inline delete confirm. Numbers such as the chunk size, the
   polling interval and the price come from `/api/config`, not from the web code.
   **Literals (D76):** ESLint errors on `no-magic-numbers` (ignore -1, 0, 1, 2; array indexes),
   `react/jsx-no-literals` (no strings in JSX), and `no-restricted-syntax` for string literals that look
   like URLs or hex colours. A policy test runs `npx eslint --print-config` on one `.tsx` file and fails
   unless those three rules are `error`. `scripts/check_literals.py` covers `.astro` text.
   **Analytics seam (D75):** `web/src/lib/analytics.ts` exports `track(event, params)`; it reads
   `analytics` from `/api/config`, does nothing while disabled, sets the consent defaults first and loads
   the Google tag only after consent. Call it at every event in `docs/UX.md` §5. No banner yet.
4. **Fake editor** for e2e: a launcher option that walks the stages with short sleeps and writes
   fixture outputs, so the UI tests cost nothing.
5. **Playwright suite** `tests/e2e/` = `docs/UX.md` §6 items 1–8 at 390×844 and 1280×800, plus axe, plus
   "analytics off: no request to any Google host".
   Item 2 (dropped chunk resumes) is written first. It runs in `make prerelease` (with Lighthouse),
   not in `make ci`; `scripts/ci-install.sh` gains the Playwright browser install only for that target.
6. **`compose.yaml` and `make up`:** api (serves web), dispatcher, Firestore emulator
   (`gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators`), Mailpit (`axllent/mailpit`, F43).
   `make down` stops everything; data in `./data/`.
7. **Privacy page** (one page): what is stored, for how long (7 and 30 days), who processes it
   (Anthropic, Google, Stripe, Resend), how to delete.
8. **Manual phone test (D17):** from an iPhone on the same Wi-Fi, open `http://<laptop-ip>:8080`, upload
   a 300 MB HEVC video from the gallery; record the result in HANDOFF.md. Then one real Reel through
   the real editor (≤ $3).

## Done when

- `python3 scripts/gates/step06.py` prints `GATE step06 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/web.md` and the pull request.
- Playwright report: all green on both sizes; axe: no serious or critical issues.
- In `docs/handoff/web.md` a line `iPhone upload: <result>` (task 8).
- Playwright keeps screenshots of failures only; look at each state once on a phone and a laptop and
  write one line per state in HANDOFF.md.
- The iPhone result and the real Reel's cost in HANDOFF.md.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/web.md`.)

This step is large: split it into two sessions if needed (tasks 1–2, then 3–8), each ending in a
merged PR. Final message: five-line status board, then the PR link.
