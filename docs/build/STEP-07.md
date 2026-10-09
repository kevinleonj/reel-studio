# STEP-07 — The Stripe gate, weekly limit, two slots and the queue

**Outcome:** on the laptop, Kevin types a Stripe test promotion code, confirms the €0 checkout, uploads
and gets a Reel; a second order waits in line while two run; the 51st checkout of a week is refused.

Lane **web**: the worktree `~/projects/reel/reel-studio-web` (`git rev-parse --show-toplevel` ends in
`/reel-studio-web`); do not leave it. Handoff file: `docs/handoff/web.md`.
Settled: D05, D22, D45, D55, D58, D63, `docs/ARCHITECTURE.md` §4 rules and §7 routes. Paid ≤ $3.

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
grep -o '^STRIPE_SECRET_KEY=' .env && stripe version     # `stripe login` was done in STEP-00
```
Look up with Context7 or docs.stripe.com, and record in FACTS.md: Checkout Session create with
`discounts` and `expires_at`, `checkout.Session.expire`, List promotion codes by `code`, webhook
signature verification in `stripe` 16.x, the API version `2026-09-30.endive` (F19–F23). Never send
`discounts` and `allow_promotion_codes` together (F21b). Branch `step-07-gate`.

## Tasks

1. **Payments port, Stripe adapter** (test mode), with the fake. During the beta the server refuses a
   code whose coupon is not 100% off (`code_invalid`), so no charge can happen.
2. **Checkout transaction:** look up the code → in one Firestore transaction check `count < cap` for the
   ISO week, increment, create the order `awaiting_payment` → create the Checkout Session (€19 price
   from `make stripe-setup`, `discounts=[{promotion_code}]`, `expires_at = now + 31 min` (one above
   Stripe's minimum, F20), success URL `/o/<order_id>?t=<token>` and cancel URL, `client_reference_id = order_id`). If Stripe fails, release
   the place in a second transaction.
3. **Fulfilment** from the webhook and from `POST /fulfil`, idempotent; **expiry** from the webhook,
   from `/cancel` and from the sweep (orders `awaiting_payment` older than 36 min are checked with
   Stripe); failed orders give the place back (D22); `paid` orders not started in 7 days become
   `abandoned` (D25); a spend-limit error pauses the service (D26).
4. **Slots and queue:** `take_slot` / `release_slot` transactions on `limits/capacity` (the take also
   writes `queue.run_token`, passed to the job with `ORDER_ID`), lease 70 min,
   queue order by `queue.queued_at`, the worker starts the next order when it ends, the sweep frees
   dead leases and fails their orders.
5. **Race tests on the emulator (write first):** 10 concurrent checkouts at count 45 with cap 50 →
   exactly 5 succeed; the same webhook delivered 3 times → one order, one email; 3 concurrent starts
   with 2 slots → exactly 2 running; a worker killed mid-run → the sweep fails it and frees the slot.
6. **`reelctl`** (`reel_studio/cli/reelctl.py`): `codes create --name <friend> --expires <YYYY-MM-DD>`
   (`max_redemptions` from `config/limits.toml` `[codes]`),
   `codes expire <code>`, `orders list [--status]`, `orders resume --all-paused`, `report --week`.
7. **Write count (A5):** count Firestore writes for one order on the emulator; record in FACTS.md.
8. **`make stripe-listen`** runs `stripe listen --print-secret` into `.env` `STRIPE_WEBHOOK_SECRET`
   without echoing it, then `stripe listen --forward-to localhost:8080/api/stripe/webhook`.
9. **End to end:** `make stripe-listen`, `PAYMENTS=stripe`,
   one real order with a test code and the real editor (≤ $3).

## Done when

- `python3 scripts/gates/step07.py` prints `GATE step07 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/web.md` and the pull request.
- Race tests green (marker `race`; paste the summary); the write count recorded; in
  `docs/handoff/web.md` a line `Stripe e2e order: <order id>, <cost>`.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/web.md`.)

Final message: five-line status board, then the PR link.
