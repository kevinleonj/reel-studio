# Handoff — lane web

Written by the web lane only. Trimmed to the open items on 16 Oct 2026 (TIDY.md); the older
entries, logs and standing-order decisions are in git history: `git log -p -- docs/handoff/web.md`.

## Status board
- READY TO MERGE: PR #24 (upload copy). CI green, senior review PASS; `gh pr merge 24 --auto
  --squash` was refused ("clean status": auto-merge needs pending checks), so Kevin merges.
- Open: the NIGHT WEB 2 fixes (crash notice, null result fields) and this trim, stacked on #24.

## Next
- The pause emails (For MAIN below) once MAIN changes its test.
- The page's empty "Text to add in Instagram" heading and empty music line when the real editor
  sends none (`web/src/components/order/Result.tsx`): hide them as `left_out` and `wishes` are
  hidden. Not done on 16 Oct: needs a Playwright case, and NIGHT ran no Playwright.

## For MAIN
- **Pause emails (D45; EDITOR.md §5 "Kevin is emailed"; UX.md §3 "Your Reel is waiting").** A
  spend-limit pause emails nobody: `RealEditor._stopped` returns before the notifier, and the
  `paused` template and `messages.paused_message` are unused. The web-lane fix is ready
  (`Notifier.order_paused`: Kevin's alert claimed as `kevin_paused`, the customer's `paused` email
  claimed as `paused`; `RealEditor` calls it; an `EditorNotifier` protocol), but
  `tests/unit/test_editor_job.py::test_the_monthly_limit_pauses_and_sends_and_starts_nothing`
  pins `assert world.sent.bodies == []`. Change that line to `assert len(world.sent.bodies) == 2`
  and the web lane lands the fix with its tests.

## Open follow-ups (from the STEP-07 reviews)
- W3: `engine_make_reel` and `dispatch(real=True)` have no unit test (patch `cli.reel.real_deps`).
- W4: reelctl's Stripe commands end in a traceback on a bad key, a docker failure or Ctrl-C.
- W5: pin `run_docker`'s capture branch, a non-404 coupon lookup, the price's idempotency key.
- W7: the test-key prefixes live in three places; `STRIPE_SECRET_TIMEOUT_S` belongs in `[stripe]`.
- S1: a fixed `STRIPE_DEVICE_NAME` for both listener containers.
- S2: a reused coupon is checked for 100% and once only; also check `valid`, `max_redemptions`,
  `redeem_by`.
- S4-S6, S10: reelctl is 377 lines (split the Stripe half out); the real editor's logs lack
  `latency_ms`; a few docstrings still say "fake"; `queue.run_token` unused on the laptop.
- The real editor sends no `text_lines`, `left_out` or `wishes`, and `doubts` carry the critic's
  raw scores (`peak 2 < 3; ...`): the engine's result shape (EDITOR.md §8).
- N3: pin that a non-alphanumeric `whsec_` value is masked and reelctl imports without Stripe.
- S9: no Gemini-key guard for `keep_voice` in `engine_make_reel`; ports 8681 and 1025 are typed
  in both `compose.yaml` and `mk/web.mk`.
- Copy test: assert the upload sentence has exactly the three placeholders (`format()` prints an
  unknown `{key}` as is).

## For CLOUD
- Late chunks are refused on the laptop only: Cloud Storage resumable sessions go straight to the
  bucket. The cloud adapter should cancel an order's open sessions at Start; the editor already
  reads only the files in the manifest (`launcher_real.py`).
- A newer upload session for a name supersedes the older on the laptop; the Cloud Storage adapter
  should cancel the older resumable session (DELETE on its session URL; check the docs first).

## Needs Kevin (decisions, not blocking)
- **Upload copy (16 Oct 2026):** `docs/UX.md` §2 (`paid` row) still quotes the old upload
  sentence; add "Vertical videos only. At least 15 seconds of video in total." there (the web
  lane cannot edit UX.md). And 15 s is the shortest Reel on offer, not enough footage for the
  30 s default: say if the sentence should name the ordered length instead (the panel gets only
  `config` today, so it needs the order's `settings.length_s` passed from `OrderPage.tsx`).
- **Merging:** the hook allows only `gh pr merge N --auto --squash`, which GitHub refuses once
  the checks have already passed. Lanes then wait for you even when everything is green.
- **Review verdict file:** a senior review cannot write `.claude/review-verdict.json` from this
  worktree (lane main's path). Add it to the shared list, or have lane main write it.
- **Laptop webhook signing secret** appeared in a local scratch log on 12 Oct (test mode,
  scrubbed, never pushed). How to rotate a CLI listen secret is not looked up; say if wanted.
- **`KEVIN_ALERT_EMAIL`** on the laptop is the placeholder `kevin@laptop.invalid`.
- **The ready email's link** (D18 edge): decided by standing orders as "open the link from your
  first email" (HANDOFF.md). Other options if you want one: an encrypted token, or a re-access flow.
- **Tunables to review:** `[firestore] timeout_s = 10`, `max_attempts = 12`; `[reelctl]
  list_limit = 200`; `[payments] price_minor = 1900`; `[upload] backoff_ms = 1000`; `[web]
  request_timeout_ms`, `chunk_timeout_ms`, `signed_url_minutes`, `rating_max`, `comment_max_chars`.
- **Ports beyond ARCHITECTURE §3:** `OrderUpkeep`, `PaymentsUpkeep`, `PaymentGateway`; confirm
  or move them into §3.
- **CI skips the Firestore/Mailpit contract cases** (`make test-emulator` runs them; the image is
  ~1 GB). Your call whether CI or a gate runs it.
- `scripts/check_literals.py` `WEB_HOMES` still exempts `web/src/lib/analytics.ts`, which holds
  no URL any more (the scanner is protected). `public/og.png` is a screenshot placeholder.

## Evidence lines (the gates read these)
iPhone upload: 345 MiB HEVC .mov from Photos, Safari, home Wi-Fi, complete in 9 min 4 s (0.66 MB/s; server side measured fast, likely the phone's Wi-Fi) (Kevin, 13 Oct 2026)
Stripe e2e order: c86d1bf26052af262931df7ab248a8c5, $0.3587172 (12 Oct 2026, Stripe test mode, a friend code, €0 checkout, six clips, real editor, critic 20, render 2)

## Log
### 16 Oct 2026 — NIGHT WEB 1-3
- 1, upload copy (PR #24): the upload sentence ends "Vertical videos only. At least 15 seconds of
  video in total." (Kevin, 13 Oct; pending as D79). The test ties the 15 to `lengths_s`.
- 2, fixes: the laptop's crash handler (`FakeEditorLauncher`) now emails Kevin and the customer
  (re-review N1); the order view turns a stored null result field into its empty value (S3,
  L303). The pause emails are parked (For MAIN).
- 3, this file: 486 lines to under 80.
