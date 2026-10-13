# Handoff — lane web

Written by the web lane only. Newest entry on top.

## Status board
Nothing in this lane waits for Kevin's hands. Decisions still open are under Needs Kevin.

## Done — STEP-07 tasks 8-9 on the laptop (branch `step-07-e2e`)
- Done: `reelctl dotenv-set` writes through `./.env` when it is a symlink (a worktree's link to the shared file stays a link); `make stripe-laptop` finds or creates the €19 price (lookup key `reel-eur-1900`, the same as STEP-08's `make stripe-setup`) and the 100%-off, duration-once coupon `reel-beta-free`, then writes `STRIPE_PRICE_ID`, `STRIPE_COUPON_ID`, `PAYMENTS=stripe` (test keys only, no gcloud; run twice: created, then found); `make stripe-listen` needs no `stripe login`: the pinned Stripe CLI image gets the key on stdin and its output is masked; `make dispatch-real` runs the real editor on the host against the compose stack.
- Done: task 9, one real order through the site in Stripe test mode with a code, the €0 hosted checkout (no CAPTCHA shown; Stripe's invisible hCaptcha frame is always there), six `pastav2` clips, the real editor, the Reel on the page (Playwright, scratch script). Cost below.
- Fixed on the way: the first paid order finished but its page crashed (`music: null`; L303), and the page showed a dangling `·` for a hint without a tempo.
- Partly: the real editor's result fills `music` from `music_hint` and `doubts` from the critic, but sends no `text_lines`, `left_out` or `wishes` yet, so "Text to add in Instagram" is an empty heading and "Check before posting" shows the critic's raw scores (`peak 2 < 3; share 2 < 3; total 20 < 26`). Follow-up for the engine's result shape (EDITOR.md §8) before the cloud job.
- Blocked: nothing.

## Follow-ups from the STEP-07 e2e review (PASS, 0 critical; fixed: W1 formatter drive-by, W2
spend limit pauses instead of failing and failures email Kevin, W6 lazy Stripe import, W8 no
setting values in the real editor's startup error, W9/W10 docs, S7 no codes in the handoff, S8
mask `whsec_\S+`)
- W3: `engine_make_reel` (order settings to `make.Request`) and `dispatch(real=True)` have no unit
  test; only the paid run covers them. Patch `cli.reel.real_deps` with the engine's fakes.
- W4: reelctl's Stripe commands end in a traceback on a bad key, a docker failure or Ctrl-C;
  catch them in `main` and print one line (docker's stderr through the same masks).
- W5: pin the capture branch of `run_docker` (stdin reaches docker, timeout, non-zero exit), a
  non-404 coupon lookup, and the price's idempotency key.
- W7: the test-key prefixes exist three times (reelctl, `api/main.py`, scripts/cloud), the lookup
  key is re-derived from scripts/cloud's rule, and `STRIPE_SECRET_TIMEOUT_S` belongs in
  `[stripe]`. One home each, with the cloud lane for scripts/cloud.
- S1: give both listener containers a fixed `STRIPE_DEVICE_NAME` so the secret from
  `--print-secret` and the forwarding session share one device (they did in the run: events 200).
- S2: a reused coupon is checked for 100% and once only; also check `valid`, no
  `max_redemptions`, no `redeem_by`.
- S3: `api/views.py` forwards a stored `music: null` to the page; default it there too before the
  cloud job (STEP-08) becomes a second writer.
- S4-S6, S10: reelctl is 370 lines (split the Stripe CLI half out); the real editor's logs lack
  `latency_ms` and the full cause of a provider failure; a few docstrings still say "fake";
  `make up` after `make dispatch-real` restarts the fake dispatcher; `queue.run_token` is still
  unused (one run per order, STEP-08).
- The real editor sends no `text_lines`, `left_out` or `wishes` (see Partly above).
- Re-review N1: an unexpected exception in the real editor fails the order through the
  launcher's crash handler, which sends no notice; EDITOR.md §10 says every failure
  emails Kevin. Give that handler the notifier.
- Re-review N2: a spend-limit pause sends Kevin nothing; EDITOR.md and D45 say he is
  emailed. Add a Kevin-only `service_paused` notice.
- Re-review N3: pin the new fixes (a non-alphanumeric `whsec_` value is masked; reelctl
  imports without the Stripe SDK, in a subprocess; `build_dispatcher` wires the real
  notifier; a notifier that raises is logged).
- S9 and ports: no Gemini-key guard for `keep_voice` in `engine_make_reel` (as
  `cli/reel.py` has); ports 8681 and 1025 are typed in both `compose.yaml` and
  `mk/web.mk`.

## Done — STEP-07 (branch `step-07-gate`)
- Done: task 2 (checkout with a code, place reserved with the order, released if Stripe fails), task 3 (fulfilment from the webhook, `/fulfil` and the sweep; expiry from the webhook, `/cancel` and the sweep, which asks Stripe first), task 4 (slots and queue: built in STEP-06, now under race tests; `take_slot` writes `queue.run_token`, but nothing passes it to the job yet: that is the real launcher's, with the engine lane's worker command), task 5 (4 race tests, fake and Firestore emulator), task 6 (`reelctl` commands on the ports), task 7 (write count: 19, F312), task 8's make target (`make stripe-listen`, dry-run only); `/api/config` sends the €19 price in Stripe mode.
- Also done: task 1, the Stripe adapter (`adapters/payments_stripe.py`, test mode, 22 tests through the real StripeClient and a recording HTTP client), the Stripe composition root (`main.build_payments`) and `reelctl connect()`; REVIEW-FIXES.md WEB items 1-5 and the npm audit triage; the review round 1 fixes (below).

## Decided by standing orders (STEP-07 and REVIEW-FIXES)
- `make stripe-listen` hands the key to the Stripe CLI as `STRIPE_API_KEY` on stdin (`docker run -i --env-file /dev/stdin`), not with `--api-key`: an argument shows in `ps` on the host. (The container's own environment still holds it while the listener runs, as with any env-file value.) The CLI's own docs name `STRIPE_API_KEY` for Docker (F322). Undo: pass `--api-key` in `reelctl.stripe_listen`.
- The Stripe CLI runs from a digest-pinned image (`[stripe] cli_image`, v1.52.0), not a host install, so the laptop needs only Docker. Undo: call a host `stripe` in `run_docker`.
- Laptop Stripe setup is `make stripe-laptop` (reelctl `stripe-setup`), not a mode of `scripts/cloud/stripe_setup.py`: that file is the cloud lane's. Both use the same lookup key, so they share one price. Undo: move the code there when the cloud lane wants it.
- `KEVIN_ALERT_EMAIL` in the shared `.env` was empty and WebSettings requires it, so reelctl could not start; it is now the placeholder `kevin@laptop.invalid` (a reserved domain, nothing is delivered). Set your address before STEP-08. Undo: `printf '%s' <address> | uv run reelctl dotenv-set KEVIN_ALERT_EMAIL`.
- Host processes (`make stripe-laptop`, `stripe-listen`, `dispatch-real`) get `SMTP_HOST`, `SMTP_PORT`, `DATA_DIR`, `WEB_DIST` and `FIRESTORE_EMULATOR_HOST` from `LAPTOP_HOST` in `mk/web.mk`, the host's view of the compose stack, so `.env` keeps no laptop-only values. Compose publishes the emulator (8681) and Mailpit's SMTP (1025) on 127.0.0.1 only. Undo: drop `LAPTOP_HOST` and the two port lines.
- The laptop's real editor runs in the host dispatcher (`make dispatch-real` stops the compose dispatcher), because the api image has no editor extra and no Anthropic key (D62). Undo: `make up` again.
- `stripe_setup` refuses any key that is not `sk_test_`/`rk_test_`. Undo: not advised (D58).
- Upload limits: every `/uploads` batch reserves its declared names and sizes on the order (`uploads`, `OrderUpkeep.reserve_uploads`, one transaction), keyed by the exact stored name; asking again for a name never lowers its reservation; names are checked before anything is reserved. Start still re-checks the finished files. Undo: revert the item-1 and round-1 commits.
- A newer upload session for a name closes the older one and its bytes (the storage contract changed from Cloud Storage's "last completed wins"; see For CLOUD). The session index (`_current_file`, `_is_current`, `_commit` in `storage_local.py`) holds the live session per name; a session opened before the index existed is refused with 404 and its partial bytes stay until the order is deleted. Undo: drop the index and restore the three contract tests.
- A transaction that runs out of attempts on a busy order answers 503 `busy` with `Retry-After` (`[web] busy_retry_after_s = 2`), not 500. Undo: remove `on_busy`.
- A Checkout Session whose `amount_total` is not 0 is expired at once and the code refused (`code_invalid`): D58's no-charge rule checked on Stripe's own total. Undo: remove the check in `payments.checkout`.
- Stripe client: `[stripe] timeout_s = 20`, `max_network_retries = 2`, `webhook_tolerance_s = 300` (F321). A friend's code is `NAME-XXXXXX` (`PROMO_CODE_SUFFIX_BYTES`). Undo: edit the values.
- A chunk for an order that is no longer `paid` answers 409 `wrong_status`, status queries too. Undo: revert the item-2 commit.
- An address a mail header refuses is a 422 `invalid_request` at checkout, like the other address checks (the review said 400; 422 is what this API answers for every bad body). Undo: change `invalid()` there.
- File names over 255 UTF-8 bytes answer 400 `name_too_long` with the file, and the page says "{name} has a name too long to store. Rename it and choose it again." (new words, not in UX.md §2). Undo: revert the item-4 commit.
- npm audit (7 high): one chain, `braces` ReDoS via `micromatch`/`fast-glob`, all under the `shadcn` CLI. The site imports only `shadcn/tailwind.css` at build time and ships static files, so nothing of it runs in production or on user input. Accepted; `npm audit fix --force` would change shadcn's major. Revisit when shadcn ships a fixed range.

## For CLOUD (REVIEW-FIXES WEB 2 and STEP-07 review round 1)
- The storage contract now says a newer session for a name supersedes the older: the Cloud Storage adapter must cancel the older resumable session (DELETE on its session URL; check the docs first). `gcp_storage.create_upload_session` also returns `{key, url}` where the routes read `name`/`upload_url`, and reads `content_type` the routes do not send (review round 1 suggestion); reconcile before the cloud composition root.
- Late chunks are refused on the laptop only: Cloud Storage resumable sessions go straight to the bucket. The cloud Storage adapter should cancel an order's open sessions at Start, or the editor should read only the files in the manifest.

## Done — STEP-06 task 6 (PR #8, merged 11 Oct 2026)
- Done: task 6. `make up` builds `docker/api.Dockerfile` (web build stage + api), starts api (serves the site), dispatcher (fake editor), Firestore emulator and Mailpit from `compose.yaml`, and waits until the api is healthy; `make down` stops everything; uploads and results in `./data/`. Composition root `reel_studio/api/main.py` (`create` for uvicorn, `dispatch` for the dispatcher), tested with fakes.
- Done since: task 8 (Kevin's iPhone upload, 13 Oct 2026, Evidence lines) and analytics off on the laptop (12 Oct 2026).
- Blocked: nothing else.
- Next: STEP-07 (above).

## Decided by standing orders (STEP-06 task 6)
- The laptop's signed-link key is random per process (`SIGNING_KEY_BYTES`): links are re-signed on every status poll, so a restart only breaks links that were about to be replaced, and there is no key to store. Undo: add a `LOCAL_SIGNING_KEY` setting and pass it in `main._storage`.
- Orders live in the Firestore emulator's memory; `make down` forgets them while `./data/` keeps the files. Undo: add an export/import volume to the `firestore` service.
- The dispatcher runs the fake editor (STEP-06 task 4) until the engine lane's worker command exists. Undo: swap `FakeEditorLauncher` in `main.build_dispatcher`.
- `[firestore] max_attempts = 12`, not 5: STEP-07's emulator race test lost 8 of 10 checkouts with 5 (an aborted transaction retries at once with its old id, so N writers need N attempts). Undo: edit the value.
- `make up` runs `python -m reel_studio.api.main check` in the built image first: WebSettings' own rules, bad names printed, values never. Undo: delete that line in `mk/web.mk`.
- Compose passes each WebSettings name on purpose (the `x-website-settings` block), no `env_file`, so the Anthropic, Gemini and cloud keys never reach the website (D62). The dispatcher gets the same block; when the real editor lands it needs the Anthropic key added to its own `environment` only. Undo: not advised.
- api and dispatcher run as the host user (`HOST_UID`/`HOST_GID` from `make up`, default the image's 10001), so `./data` is writable on Linux as well as macOS. Undo: drop the two `user:` lines.
- Mailpit's inbox is published on 127.0.0.1 only: it holds every order link. Only the site (8080) is on every interface (D17).
- Stopping the dispatcher does not wait for an order the fake editor is running; it stays `running` until the lease sweep fails it (70 min). The real editor runs as its own job in the cloud, so this is a laptop-only cost. Undo: join the run threads in `dispatch()`.

## Done — STEP-06 (PR #4, merged)
- Tasks 1-5 and 7; task 6 in PR #8; task 8 is Kevin's (Status board).

## For CLOUD (the same image on Cloud Run, STEP-08)
- `docker/api.Dockerfile` needs `--build-arg SITE_URL=<the service URL>` (F61); without it the build stops with "build arg SITE_URL is required". `.github/workflows/deploy.yml` builds it without one today.
- `WebSettings` now requires `FIRESTORE_PROJECT`, `SMTP_HOST`, `SMTP_PORT`, `DATA_DIR`, `WEB_DIST`, `VOICE_AVAILABLE`; `infra/main/locals.tf` sets none of them. `reel_studio/api/main.py` is the laptop root (LocalStorage, SMTP); the cloud root (GCS, Resend, Stripe) is still to write, and `create()` builds the Stripe adapter with `PAYMENTS=stripe`.
- Rate limits key on the client address; uvicorn trusts forwarded headers only from 127.0.0.1 unless `FORWARDED_ALLOW_IPS` is set (F316). Set it on the Cloud Run service, or every client shares one bucket.


## Needs Kevin (decisions, not blocking)
- **Review verdict file:** the senior review could not write `.claude/review-verdict.json` from this
  worktree (the lane guard says it is lane main's). Its verdict, for the record: PASS, 0 critical,
  on the diff before the fixes above. Add the path to the shared list, or have lane main write it.
- **Laptop webhook signing secret:** it appeared in a local scratch log (test mode, scrubbed, no
  remote; Log 12 Oct). It does not change between restarts (F313). How to rotate a CLI listen secret
  is not looked up (it is not a dashboard endpoint secret); say if you want it done.
- **`KEVIN_ALERT_EMAIL`** is the placeholder `kevin@laptop.invalid` (Decided above); set your
  address before STEP-08.
- **Decision on D18's edge (link email after Stripe):** the webhook does not know the link token, which is stored only as a hash. The success URL Stripe keeps (`/o/<id>?t=<token>`, as STEP-07 specifies) does carry it, so fulfilment reads it back from the retrieved session, checks it against the stored hash, and sends `/o/<id>#t=<token>`. No new copy of the token is stored. Confirm, or pick another way (this also answers the "ready" email question below if the editor may call Stripe).
- **More STEP-07 tunables in `config/limits.toml` to review:** `[firestore] timeout_s = 10`, `max_attempts = 12` (an aborted transaction retries at once keeping its place in line, so N simultaneous writers on the week document need up to N attempts; with 5, 8 of the 10 racing checkouts failed on the emulator), `[reelctl] list_limit = 200`, `[payments] price_minor = 1900`, `currency = "EUR"`.
- **Port changes:** `PaymentsUpkeep` (`expire_session`, `create_code`, `expire_code`) and `PaymentGateway` beside the pinned `Payments`; `OrderUpkeep` gained `set_checkout`, `checkouts_to_check`, `resume_paused`, `list_orders`, `places_held`, and `sweep(*, expire_checkouts)` (with Stripe the API checks missed checkouts at Stripe before they expire, so a paid checkout whose webhook was lost is not dropped). New `reelctl dotenv-set NAME` (value from stdin) for `make stripe-listen`.

- **New tunables in `config/limits.toml` to review (added 10 Oct 2026):** `[upload] backoff_ms = 1000`; `[web] request_timeout_ms = 15000`, `chunk_timeout_ms = 90000` (one 8 MiB chunk at 1 Mbit/s ≈ 67 s), `signed_url_minutes = 60`, `rating_max = 5`, `comment_max_chars = 1000` (both ARCHITECTURE §7), `google_tag_url` (F70). `core/config.py` models them.
- **New ports beyond ARCHITECTURE §3's list:** `OrderUpkeep` in `core/ports.py` (`mark_viewed`, `set_feedback`, `mark_deleted`, `sweep`, `queue_position`) — kept separate so STEP-01's binding-method test for `Orders` stays as pinned. Please confirm or move them into §3.
- `.claude/doc-ledger.json`: the global doc gate (`~/.claude/hooks/gate-docs.sh`) reads `<session cwd>/.claude/doc-ledger.json`, which is outside every lane and hook-protected. Kevin installed it by hand on 9 Oct 2026. Pending entries for phase B are in `web/doc-ledger.pending.json` (git-ignored). The gate misreads multi-line `import type {` as a library named `type`, and `node:fs`/`node:path` as non-stdlib.
- `scripts/check_literals.py` `WEB_HOMES` still exempts `web/src/lib/analytics.ts`, which no longer holds a URL (the tag URL arrives from `/api/config`); the scanner is protected.
- `public/og.png` is a 1200×630 screenshot of the landing page; replace it with real artwork when there is some.
- **The "ready" email cannot carry the order link.** Its button needs `/o/<id>#t=<token>`, but the token is stored only as its SHA-256 (D18), so the editor or the dispatcher cannot rebuild the link after checkout. Options: the ready email says "open the link from your first email"; or keep the token encrypted with a server key; or a short re-access flow. A decision on D18's edge; until then the fake editor sends no ready email (failure emails and Kevin's alert need no token and are sent).
- **CI does not run the Firestore/Mailpit contract cases** (they skip without the emulators; `make test-emulator` runs them and now fails instead of skipping). Adding it to `make ci` means pulling the ~1 GB gcloud emulator image on every CI run (20-minute job limit); or the step06 gate could run `make test-emulator`. Your call; the gate is protected.
- **For the composition root (after the settings fields):** run uvicorn with `access_log=False` (its access log prints path and query: signed-link `sig=` and Stripe's `?t=`); behind Cloud Run use `--proxy-headers` with a trusted-hosts list so rate limits see the client, not the front end; give the dispatcher a restart policy in compose. Tunables still without a home: dispatcher poll seconds, SMTP `timeout_s` (Firestore's are in `[firestore]` since STEP-07) (this lane can add them to `config/limits.toml` with the composition root).
- Kevin's global hook commits every edit as `chore(auto)`; the branch was rebuilt into logical commits on top of `origin/main` before the push (TONIGHT.md rule).

## Evidence lines (the gates read these)
iPhone upload: 345 MiB HEVC .mov from Photos, Safari, home Wi-Fi, complete in 9 min 4 s (0.66 MB/s; server side measured fast, likely the phone's Wi-Fi) (Kevin, 13 Oct 2026)
Stripe e2e order: c86d1bf26052af262931df7ab248a8c5, $0.3587172 (12 Oct 2026, Stripe test mode, a friend code, €0 checkout, six clips, real editor, critic 20, render 2)

## Log

### 13 Oct 2026 — why the iPhone upload ran at 0.66 MB/s; one real Reel for the phone

- The phone's Wi-Fi was the bottleneck, not the server. The same 345 MiB clip
  (IMG_0266.mov, 361,733,068 bytes) went from this Mac through the real flow (payments off:
  checkout, `/uploads`, 44 PUTs of 8 MiB with Content-Range, like the browser) in 2.2 s
  (162.5 MB/s) to `localhost:8080` and in 2.1 s (170.6 MB/s) to `192.168.0.54:8080`, the
  address the phone used. Per chunk: median 0.046 s, max 0.082 s; checkout 0.06-0.25 s,
  upload session 0.02-0.03 s. That is about 250 times the phone's rate, so nothing to fix
  here. Caveat: the Mac reaches its own LAN address without the radio, so this proves the
  site and Docker's published port, not the Wi-Fi path.
- One real Reel from that clip via `make dispatch-real`: order
  `1338562be0ce1d62aa2ce58265d640a8`, done (render 2, critic 12, $0.2460; one clip gives the
  critic little to work with). Link given to Kevin for the phone.
- Stripe put back: `make up` with no overrides; `/api/config` says `"payments":"stripe"`.
  The order above survived (the emulator container was not recreated).
- STEP-07 paid total: $0.7209 + $0.2460 = $0.9669 of $3.
- MAIN landed the `**/.claude/state/` pattern (#17); the For MAIN item is removed.

### 13 Oct 2026 — STEP-06 task 8: the iPhone upload (Kevin)

- Before: the Status board's only item. After: done by Kevin, with the line above. A 345 MiB
  HEVC clip from Photos in Safari over home Wi-Fi completed in 9 min 4 s (0.66 MB/s). He found
  the server side fast, so the limit is likely the phone's Wi-Fi link. No resume was needed.

### 12 Oct 2026 — STEP-07 tasks 8-9 on the laptop (branch `step-07-e2e`)

- Before: Status board items 1-3 waited for Kevin (`stripe login`, dashboard values, the paid order).
  After: all three are code and were run; only the iPhone upload is left (item 5, analytics, was
  already off: `WebSettings().ga4_measurement_id` is empty).
- Run: `make stripe-laptop` created the price and the coupon, a second run found both; `.env` is
  still a symlink. `make up`, `make stripe-listen` (events answered 200), `make dispatch-real`.
  Order `ba76b749…` reached `done` ($0.3622) but the page crashed on `music: null`;
  fixed test first (L303), rebuilt, order `c86d1bf2…` showed the Reel. Paid
  total $0.7209 of the $3 budget.
- Incident: the Stripe CLI's "Ready!" line printed the test-mode webhook signing secret into a
  local scratch log. Not in a commit, a remote or the conversation; the API key never appeared.
  Stopped the listener, scrubbed the log (0 left), masked every listener line (L304), and the
  restarted listener's log shows `whsec_<redacted>`. The secret is test mode and reached no remote,
  so it was not rotated; it does not change between restarts (F313), so if you want it rotated anyway, that is your call (Needs Kevin).
- The Stripe setup calls go through the adapter's wrapper (`_timed`, `_call`): one line with latency
  each where logging is configured (the api); reelctl does not configure logging, so on the
  command line only failures surface.

### 11 Oct 2026 (night) — STEP-07 review round 3: PASS; follow-ups (branch `step-07-followups`)

- PR #11 opened and queued with `gh pr merge 11 --auto --squash`.
- Round 3's warnings fixed on the follow-up branch: a session index (`sessions/current/<order>/
  <sha256(name)>`) replaces the scan of every record, and every record write and the final move in
  `put_chunk` happen under the lock only while that session is still the name's live one, so a
  chunk in flight cannot revive a closed session (two tests, one with the race forced). Suggestions
  taken: the header test lists its five exception types itself; every order write route (uploads,
  start, viewed, feedback, delete, fulfil, cancel) shares the one-at-a-time bound; the model-level
  settings message is pinned.
- Review round 4: PASS. Also fixed: the order's write slot is released before the answer is
  sent (`scope="function"`; a client's next write was sometimes refused by its own previous
  one), the commit guard, its lock, the cleanup of refused bytes and the no-index rule are each
  pinned, and `delete_order` removes the index first under the lock without swallowing errors.
- Review round 5: PASS with one regression fixed: that reorder ran `rmtree` on an unchecked order
  id (`../..` would have emptied `data/`; unreachable over HTTP, which only passes 32-hex ids). An
  order id must now be one path part (`one_part`), checked before anything is removed; pinned.

### 11 Oct 2026 (night) — STEP-07 review round 2: FAIL (1 critical), fixed

- Critical: my merge of main duplicated `STRIPE_PRICE_ID`/`STRIPE_COUPON_ID` in `compose.yaml`, so
  Compose refused the file and `make up` was dead; the compose test now fails on a repeated key
  (PyYAML keeps the last). Fixed and run: `make up`, order to done, link email in Mailpit.
- Warnings: one live session per name now holds under concurrency (a lock; threaded test); a second
  `/uploads` for an order already in flight answers 503 at once (`InFlight`), so contention no
  longer holds worker threads; the header guard is pinned for every member of `HEADER_ERRORS`
  whatever the Python's parser; the Stripe client's version, timeout and retries, the code's
  randomness and `expire_code`'s active filter are pinned; an unknown `amount_total` is refused;
  re-picking a file in the page replaces its row (Playwright).
- Suggestions taken: the webhook secret stays out of `StripeSetup`'s repr; live-mode keys are
  refused (test mode only, D58); `reelctl connect()` names missing settings without values; the
  Stripe knobs must be positive (tolerance 0 would turn off the replay check). Not taken: a cap on
  the webhook body before the signature check (inherited, every JSON route is the same).

### 11 Oct 2026 (night) — STEP-07 review round 1 fixed, Stripe adapter, Stripe composition root

Review of the rebased branch: FAIL, 1 critical (the upload reservation could be bypassed by asking
again at size 0, or by re-asking a name for more sessions), 5 warnings (contention answered 500;
a refused name left a reservation; the address check missed AttributeError/IndexError; the race
guard, the composed sweep and the Stripe refusal were unpinned; the copy contract and FACTS lacked
`name_too_long`). All fixed with tests (see Decided above; L301, L302, F320). Then main's STEP-03
and its `STRIPE_PRICE_ID`/`STRIPE_COUPON_ID` were merged, and task 1 finished: the Stripe adapter
(F19-F24, F311, F321), the D58 check on `amount_total`, `main.build_payments` and `reelctl
connect()`. Evidence: `make test-fast` 837 passed, adapter suite 22 passed, `make test-emulator`
35 passed.

### 11 Oct 2026 — STEP-07 rebased on main; REVIEW-FIXES WEB items 1-5

Before: STEP-07's five commits sat on the old `step-06-website` (pre-#4); the review of PR #4 listed
five web defects. After: the five commits replayed on origin/main (conflicts in `core/constants.py`
and `core/errors.py`, both sides kept). Items, test first, one commit each: 1 upload reservations
(fake + Firestore emulator); 2 late chunks refused; 3 crafted address refused before the order, and
the mailer builds the message inside its try; 4 names limited in bytes with their own message; 5 the
chmod test skips as root. Evidence: `make test-fast` 636 passed; `make test-emulator` 34 passed
(includes the reservation contract on Firestore); `pytest -m race` 5 passed, 5 skipped.
F312's count (19) leaves out `/uploads`: each batch is now one more write.

### 10 Oct 2026 (night) — STEP-07 review round 2: PASS with 1 warning, fixed

- R2-W1 the round-1 reorder let a Stripe-phase failure (listing the checkouts) discard the local
  report, losing the failure notices of dead leases already failed; the Stripe phase is now guarded and
  the report always returned (test: dead lease + failing listing). S3 the "completed but expired" error
  log is pinned; S5 `report --week` names an unreadable cost instead of crashing. Not taken:
  `STRIPE_EVENTS` in mk/web.mk repeats the two event names in `api/payments.py` (no test ties them).

### 10 Oct 2026 (night) — STEP-07 review round 1: PASS with 6 warnings, fixed

- W1 the sweep frees dead leases first, then checks Stripe; one checkout that errors (any error, logged)
  is kept for the next sweep and the others are still checked. W2 events other than completed/expired
  are acknowledged before any key is read; `make stripe-listen` forwards only those two (`--events`,
  F313). W3 pins for complete-but-unpaid, the 502s (webhook, /fulfil, /cancel, code lookup), the link
  token check, the expired-order guard, webhook 404 with payments off, /cancel's status gate,
  dotenv-set's guards, the report's truncation note, and a direct 3-thread `claim_email` race (fake +
  emulator). W4 `report --week` reads the week counter (`places_held`, new on `OrderUpkeep`) and sums
  finished costs as Decimal. W5 `PaymentsFailed` says adapters raise it `from None` (the log prints the
  chain; a vendor message may echo the success URL). W6 run_token, commit-timeout and price comments
  corrected. A fulfilled session whose order had already expired now logs an ERROR.
- Not taken (suggestions, for the Stripe adapter's review): cap the webhook body before the signature
  check; refuse a session whose `amount_total` is not 0 (D58 defence in depth); tell "session not found"
  from "Stripe unreachable" in the sweep; pin `payment_method_types=["card"]`; release the link-email
  claim when delivery fails; `orders_firestore.py` is 377 lines (split by concern later).
- **For Kevin:** the reviewer's mutation run copied the repository, including its secrets file, into this
  session's scratchpad (`.../scratchpad/mut_tree`, owner-only permissions; never read or printed). The
  hooks block deleting it from here: `rm -rf` that folder (full path in the session notes).

### 10 Oct 2026 (night) — STEP-07 built test first on fakes and the emulator

Before: `PAYMENTS=stripe` answered 501; `/fulfil` did nothing; `/cancel` only expired the order; the sweep
expired missed checkouts without asking anyone; `reelctl` printed its help; no race tests.
After:
- `reel_studio/api/payments.py`: checkout (code lookup, 100%-off rule, order + place in one transaction,
  session with `expires_at` +31 min, success/cancel URLs, `client_reference_id`; on a Stripe error the
  place is given back), `fulfil` (re-reads the session; pays only `complete` + `paid`/`no_payment_required`
  and only the order the session names; one link email), webhook route (signature → 400, unknown types
  acknowledged, a Stripe error answers 502 so Stripe redelivers), `cancel` (expires an open session first;
  a session completed meanwhile is fulfilled and `/cancel` answers 409), and the sweep's Stripe check (a
  checkout Stripe could not be asked about is kept for the next sweep). The dispatcher takes the sweep as a
  `Sweep(run, every_s)`, so the laptop sweep asks Stripe too.
- Race tests `tests/contract/test_races.py` (marker `race`): fake 4 passed, Firestore emulator 4 passed.
  The emulator run found the burst problem fixed by `[firestore] max_attempts` (see Needs Kevin).
- `reelctl`: `codes create --name --expires` (code works through the given day, UTC; `max_redemptions`
  from `[codes]`), `codes expire`, `orders list [--status]`, `orders resume --all-paused`, `report --week`,
  `dotenv-set`. 12 tests on the fakes.
- Write count 19 per order on the emulator (F312; A5 assumed about 17), pinned by
  `tests/contract/test_write_count.py`.
- Evidence: `make test-fast` 328 passed; `pytest -m race` 4 passed, 4 skipped (emulator cases);
  `make test-emulator` 31 passed; ruff, mypy (74 files), literal scan clean.
Follow-ups: the Stripe adapter and its fixture tests (`stripe` ledger entry); `reelctl connect()`; task 9.

### 10 Oct 2026 (night) — STEP-07 plan (stacked branch `step-07-gate`, not pushed)

TONIGHT.md's web section changed during the night: the version read at 22:45 said to push and open
the pull request after STEP-06 (done: PR #4, CI green); the current one says "No push tonight" and adds
this stacked STEP-07. PR #4 stays open; nothing on `step-07-gate` is pushed.

Plan, test first, fakes and Stripe fixtures only (no Stripe call tonight; `stripe login`,
`make stripe-listen`, the laptop checkout and the paid Reel are Kevin's):
1. Payments port shapes settle (`core/ports.py`): `find_code` → `{promo_id, code, percent_off, active}`
   or None; `create_checkout` → `{session_id, url}`; `parse_webhook` → `{type, session_id, order_id}`;
   `get_session` → `{status, payment_status, order_id, email}`. Expiring a session and the reelctl code
   commands go in a `PaymentsUpkeep` Protocol beside it (STEP-01 pins the binding list). Fake in
   `tests/fakes/payments.py`; Stripe adapter `reel_studio/adapters/payments_stripe.py` (F19-F24, F311).
2. Checkout with `PAYMENTS=stripe` (routes_public): refuse a code that is not 100% off (`code_invalid`) or
   inactive (`code_inactive`), reserve the place and create the order in one transaction, create the
   session (€19 price id from settings, `expires_at = now + 31 min`, success `/o/<id>?t=<token>`, cancel
   `/new?cancel=<id>&t=<token>`), release the place if Stripe fails.
3. Webhook `POST /api/stripe/webhook` (signature), `/fulfil` checks the session with Stripe, `/cancel`
   expires it, the sweep asks Stripe about missed checkouts before expiring them. All idempotent.
4. Race tests (marker `race`, fake + Firestore emulator): 10 concurrent checkouts at 45 of 50 → exactly
   5; one webhook delivered 3 times → one paid order, one email; 3 concurrent starts with 2 slots →
   exactly 2 running; a worker killed mid-run → the sweep fails it and frees the slot.
5. `reelctl` (`codes create --name --expires`, `codes expire`, `orders list [--status]`,
   `orders resume --all-paused`, `report --week`) on the ports; `make stripe-listen` in mk/web.mk.
6. Write count for one order on the emulator (A5) into FACTS.
Blocked the same way as STEP-06 task 6: the composition root needs the `WebSettings` fields, plus a
Stripe price id setting (`stripe_price_id`, from `make stripe-setup`, STEP-08).

### 11 Oct 2026 — STEP-06 task 6: make up

Before: no way to run the site except the test fixtures; task 6 waited on the WebSettings fields (PR #6).
After: `reel_studio/api/main.py` builds the API and the dispatcher from WebSettings + config
(`[firestore]`, `[smtp]`, `[dispatcher]` added to `config/limits.toml`); `docker/api.Dockerfile`
(node 24.21.0 stage builds `web/dist`, F314; uvicorn `--factory`, `--no-access-log`, F316);
`compose.yaml` (F315); `make up`/`make down`. `routes_local` exports its two paths so the storage
adapter and the routes cannot disagree.
Review round 1 FAILED (2 critical: Mailpit's inbox on every interface, `env_file` handing every
key to the website against D62; 8 warnings) and was fixed: explicit settings names, loopback
Mailpit, restart policy on all four services, host uid, `check` inside the image instead of a
names-only preflight, a named logger (under `python -m` the module is `__main__`), a stop handler that
only sets the event, Stripe refused before the Firestore client, tests that run every fake stage, a
chunk and a signed download through the composed app, and `compose.yaml`'s safety properties.
Evidence, on the committed compose (`make up` exit 0, `check` printed `settings ok`): `/` and
`/privacy` 200, `/new` and `/o/gate-check` 200 with `noindex, nofollow`; a PAYMENTS=off order went
checkout → chunk 200 → start → queued → running (reading) → done; signed download 200; Mailpit got
"Your Reel Studio link". Order `385afc5981872f15509e2f44b23b2af4`. From the laptop's LAN address the
site answers 200 and Mailpit does not answer; neither container has the Anthropic, Gemini, Resend
or Cloudflare names; both run as uid 501; the dispatcher logged "dispatcher started" and, on
`docker compose stop`, "dispatcher stopped" and exited 0.
Review round 2: PASS (2 warnings). Follow-ups: tests for the remaining wiring (SMTP timeout, notifier, sweep interval, a link from one app refused by another); `check` should name model-level errors (PAYMENTS=stripe without keys prints no name) and mirror the Stripe refusal; the compose port test should assert which services have `ports:`; Stripe names only for the api; a dispatcher heartbeat healthcheck; SIGTERM is not honoured while a Firestore call blocks (emulator gone), so `docker stop` ends in SIGKILL; files of orders forgotten by `make down` stay in `./data/` (delete by hand); `next_queued` logs one INFO line per 2 s poll. Not run: the step06 gate (needs task 8 and
analytics off on the laptop) and `make prerelease` (web/ is unchanged since PR #4, where it passed).
For MAIN: `.dockerignore` (REVIEW-FIXES MAIN item 2) still missing; the api image copies named paths
only, but the build context still carries `.env` to the Docker daemon.

### 10 Oct 2026 (night) — phase B review round 3: PASS with 4 warnings, fixed

- R3-W1 Kevin's alert is sent first and needs nothing from the copy table; a customer failure email that
  cannot be built is logged and stays unclaimed. Nothing retries it later: the sweep reports an order
  once (the round-2 note below said otherwise; it was wrong). R3-W2 the down-mailer and log-leak tests
  now fail the order first, so they reach the Notifier's own sends. R3-W3 pins for the dispatcher's
  per-order guard, NFC names, the rate-limiter prune, "bytes nowhere is not complete", an older session
  replayed after a newer upload, the Start bytes re-check and the store's path guard
  (`tests/unit/api/test_api_pins_r3.py`). R3-W4 F310 now quotes the right Google page. Also: a status
  query reports a short partial truthfully (it used to overstate or answer 400), file names longer than
  255 characters are refused at the batch, the delete-skip log no longer carries the session id.

### 10 Oct 2026 (night) — phase B re-review: PASS with 7 warnings, fixed

- R2-W1 an SMTP refusal's traceback carried the recipient's address into the JSON log: `DeliveryFailed`
  is now raised `from None` (test asserts the address is in no log line). R2-W2 the failure email is
  built before it is claimed (see round 3: Kevin's alert no longer depends on it), only orders that
  really failed get it, one order's notice error no longer skips the rest; `messages.py` reads
  `web/src/copy/en.json`, so **the api image must COPY that file** (test pins that it exists). R2-W3 a
  256-character path or session id is a 404, not a 500. R2-W4 session records are written via a temp
  file and rename; an unreadable record of another order no longer blocks a delete. R2-W5 `Clip.MOV` and
  `clip.mov` in one batch are refused (APFS treats them as one file). R2-W6 pins for every surviving
  mutant the review listed (SMTP mapping, claim-once, concurrent Start, delete guards, exact-limit chunk,
  batch accounting, partial removal). R2-W7 the rate limiter forgets idle addresses once per minute.
  Also: a partial shorter than its record is reported and resent, not zero-filled; a crash after the
  move answers complete on retry; the emulator runner always stops both containers.

### 10 Oct 2026 (night) — phase B senior review: FAIL (1 critical, 10 warnings), fixed

- C1 the laptop's partial upload belonged to the file name: a re-chosen file could interleave, be
  dropped or grow. Now each session keeps its own partial (truncated to the recorded offset before
  every write), the finished file replaces any older one (last wins, as in Cloud Storage), a batch may
  not name a file twice. Contract case "same name twice" plus three protocol regression cases.
- W1 a mail server that is down no longer turns a created order into a 500 (typed `DeliveryFailed`;
  logged); emails are shape-checked (no CR/LF) before any order exists. W2 a failing dispatcher tick is
  logged and retried; any launch error fails the order and frees the slot. W3 no unauthenticated 500s
  (non-ASCII signature, wrongly typed settings, NUL in paths). W4 a second Start answers 200. W5 Start
  re-checks file count and bytes on what arrived. W6 a failed delete propagates and can be retried; the
  status never says "deleted" while files remain. W7 `expires_at` for the Firestore TTL; one email per
  outcome (`claim_email`); failure emails to the customer and Kevin from the sweep and launch failures
  (`reel_studio/api/notify.py`, words from `en.json`). W8 tests for every signed field, a raw `..`
  path, request-log hygiene, first-come FIFO, every guard, a wrong token on every order route. W9 a late
  pause pauses the service on both adapters; emulator cases fail instead of skipping under
  `make test-emulator`. W10 a chunked body is counted as it streams.
- Suggestions taken: `fullmatch` for order ids, HEAD on the site, typed rate-limiter deque, the cap
  refreshed mid-week, expected refusals logged at INFO, `limits_from(config)` with a test. Not taken: S4
  (enforcing 256 KiB multiples on the laptop: the client already enforces it, F307), S8 (re-measure
  Lighthouse through the API once it serves `dist/`).

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
