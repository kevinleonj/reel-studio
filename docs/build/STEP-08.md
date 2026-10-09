# STEP-08 — Google Cloud beta (Tier 2)

**Outcome:** the beta runs at its `run.app` address; an order placed from a phone on mobile data with a
test code produces a Reel and a "ready" email from `reels@reels.limeralda.com`.

Lane **cloud**: the worktree `~/projects/reel/reel-studio-cloud` (`git rev-parse --show-toplevel` ends in
`/reel-studio-cloud`); do not leave it. Handoff file: `docs/handoff/cloud.md`.
Settled: D50–D62, all of `docs/INFRA.md`, `docs/ARCHITECTURE.md` §5–§6. Paid ≤ $3.
Before the first apply: run the reviewer agent on the Terraform and on this plan (second opinion).

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
gcloud auth list --format='value(account)' && gcloud config get-value project
grep -o '^\(GCP_BILLING_ACCOUNT\|CLOUDFLARE_API_TOKEN\|RESEND_API_KEY\)=' .env
terraform version | head -1                                  # 1.16.5
```
Query Context7 `/hashicorp/terraform-provider-google` for every resource in `docs/INFRA.md` §2 before
writing it; record argument names and defaults in FACTS.md. Branch `step-08-cloud`.

## Tasks

0. **Cloud adapters and scripts (this lane's paths):** `reel_studio/adapters/gcp_storage.py` (resumable
   upload sessions, signed downloads), `gcp_launcher.py` (Cloud Run job with overrides), `resend_mailer.py`,
   each run against the same contract suite as the local adapters with recorded responses; the scripts
   behind `make gcp-project`, `secrets-push`, `stripe-setup` and `dns` live in `scripts/cloud/`.
1. **Policy checks first:** `infra/policy/explicit_args.toml` (resource type → arguments that must be
   set, from `docs/INFRA.md` §2) and `infra/policy/locations.toml` (service → allowed regions with the
   source URL: Cloud Scheduler europe-west1, F26). `scripts/check_policy.py` fails on a missing argument,
   a wrong region, or a job above 16 GiB at 4 vCPU (F29, L7). Prove each fails on a bad fixture.
   `scripts/ci-install.sh` gains Terraform 1.16.5, tflint and Trivy at pinned versions.
2. **`make gcp-project`:** create the project, link billing, enable the bootstrap APIs (Kevin's login).
3. **Bootstrap root** (`infra/bootstrap/`, including the Artifact Registry repository and the 5 secret
   containers, `docs/INFRA.md` §1), then `make bootstrap-plan`. **Kevin applies it himself**
   with the printed command; Claude Code is denied `terraform apply`. Migrate its state to the bucket.
4. **Main root** (`infra/main/`) per `docs/INFRA.md` §2 with every argument explicit and a comment
   why; labels everywhere; the service URL built from the project number (F61), never from
   `service.uri`. `make ci` runs fmt, validate, tflint, trivy, the policy checks.
5. **Secrets and setup by API, in this order:** `make secrets-push` (cloud keys only),
   `make stripe-setup MODE=test` (cloud webhook endpoint; its signing secret goes straight to Secret
   Manager), `make dns` (Resend domain `reels.limeralda.com`, region eu-west-1, records added in
   Cloudflare as DNS-only, wait for verified, then a sending-only key straight to Secret Manager).
   Read https://ai.google.dev/gemini-api/terms and record in FACTS.md how paid-tier audio is treated.
6. **`deploy.yml`** per `docs/INFRA.md` §4 (plan job, approval, apply job, smoke). GitHub environment
   `beta` with Kevin as required reviewer, created with `gh api`.
7. **Settle the open facts with runtime evidence:** signed download URL works from the API's account
   (F34: record which IAM grant was needed); a browser upload from the service URL succeeds (F32);
   the API starts the job with overrides (F30).
8. **Outside-in:** `make smoke URL=<service url>`; then Kevin, from his phone on mobile data, places
   one order with a test code. Record job duration and peak memory (A1, A2) from the job's metrics,
   and the cold-start time of the first page load.
9. **Budget alert test:** confirm the budget exists and its email recipients (`gcloud billing budgets
   list`).

## Done when

- `python3 scripts/gates/step08.py` prints `GATE step08 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/cloud.md` and the pull request.
- `make smoke` output green (`SITE_URL` in `.env` = the service URL); in `docs/handoff/cloud.md` a line
  `Phone order: <order id>, <cost>, <duration>, <peak memory>`.
- The three settled facts recorded in FACTS.md with evidence.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/cloud.md`.)

STOP before any destroy, any IAM grant broader than `docs/ARCHITECTURE.md` §5, or any always-on cost
line not in `docs/INFRA.md` §5. Final message: five-line status board, then the PR link.
