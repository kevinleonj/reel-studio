# Handoff — lane cloud

Written by the cloud lane only. Newest entry on top.

## Status board
- Done: STEP-08 phase A (Terraform roots, policy data, deploy.yml, offline `terraform test`) and,
  after STEP-01 merged, the no-cloud part of the step: task 1 (`scripts/check_policy.py` test
  first with mutated-infra bad fixtures, `mk/cloud.mk` `ci-cloud`, `scripts/ci-install.d/cloud.sh`,
  tflint config), task 0 adapters (`gcp_storage`, `gcp_launcher`, `resend_mailer`, with fakes), the
  task 5 scripts (`make gcp-project`, `bootstrap-plan`, `secrets-push`, `stripe-setup`, `dns`,
  written and unit-tested, not run) and `scripts/smoke.py` (not run against a URL).
- Partly: task 0's "same contract suite as the local adapters": the local adapters and
  `tests/contract/` belong to the web lane (STEP-06) and are not on main; the cloud adapters are
  tested against fakes in `tests/unit/infra/` until then.
- Blocked: every task that needs the real project (2, 3 apply, 5 run, 6 environment, 7, 8, 9).
- Not started: nothing else in the step that can run without the project.
- Next: Kevin's items below, then `make gcp-project` → `make bootstrap-plan` (Kevin applies) →
  `make secrets-push` → `make stripe-setup MODE=test` → `make dns` → deploy.yml → `make smoke`.

## Needs Kevin
- **Tools on the Mac for `make ci`:** `brew upgrade terraform` (1.16.5; Homebrew has 1.16.1 and both
  roots pin `= 1.16.5`, F403), `brew install tflint trivy` (versions in F404), then
  `make tflint-init` once. CI installs all of them itself (`scripts/ci-install.d/cloud.sh`).
- **`gcloud auth application-default login`** before `make smoke` on the laptop (the step08 gate runs
  it): smoke reads the live service, job and TTL state with Application Default Credentials.
- **Launcher port changed (shared `reel_studio/core/ports.py`):** `launch(order_id, run_token)`,
  because ARCHITECTURE §4 has the launcher pass ORDER_ID and RUN_TOKEN. The web lane's local
  Dispatcher must take `run_token` too.
- **New error code `cloud_unavailable`** (`reel_studio/core/errors.py`, boundary `CloudError`): the web
  lane's copy table (`web/src/copy/en.json`) needs a message for it.
- **Wiring the cloud adapters** (which settings feed bucket, job path, origin, Resend base URL and
  sender) happens where the web lane builds its app; `reel_studio/settings.py` is the main lane's
  file, so I did not add `GCS_BUCKET` / `EDITOR_JOB` there. Terraform sets those env names
  provisionally (`infra/main/locals.tf` `common_env`).
- **`pyproject.toml` (main lane):** `google-cloud-storage` ships no `py.typed`; a mypy override for
  `google.cloud.storage.*` would replace the one local `# type: ignore[import-untyped]` in
  `gcp_storage.py`. No new dependency was needed: Resend goes over REST with httpx, secrets with
  `gcloud secrets versions add --data-file=-`.
- **Where the deployer's `roles/iam.serviceAccountUser` lives.** ARCHITECTURE §5 says bootstrap; the
  accounts are created in main (INFRA §2), so the grant is in `infra/main/iam.tf` with the same
  scope. Alternative: create the accounts in bootstrap. Your call.
- **First deploy may need a second dispatch** (IAM propagation after the actAs grant, 2-7 min).
- **Create the `beta` environment before deploy.yml reaches main** (task 6): you as required
  reviewer, branches limited to main; a missing environment is auto-created without protection.
- **Root `.gitignore`** could also carry `*.tfvars`, `tfplan.json`, `crash.log` (`infra/.gitignore`
  covers `infra/`).
- **Hooks:** the `chore(auto)` hook skips files other hooks flag, leaving half-committed trees (I
  squash before every push); `gate-hardcode.sh` has no suppression marker and flags named constants
  in `infra/*/locals.tf`, `core/constants.py` and the scripts' vendor base URLs.
- **First run of `make dns` to watch:** Resend record names are qualified as `<name>.<domain>`
  (F407); the `GET /api-keys` list shape is UNCONFIRMED (assumed like `/domains`).

## What waits for a real project (STEP-08 tasks)
- Task 2 `make gcp-project`, task 3 `make bootstrap-plan` then your apply and the state migration,
  task 5 runs, task 6 `beta` environment and repository variables, task 7 runtime facts F30/F32/F34,
  task 8 smoke and the phone order, task 9 budget check. The Gemini terms note for FACTS (task 5).

## Evidence lines (the gates read these)

## Log

### 10 Oct 2026 — STEP-08 after STEP-01 merged (no cloud access)
Before: phase A only. After (commits 41b3feb, 14b6ec8, 91da52e on top of the merge cd66765):
- `scripts/check_policy.py` (python-hcl2): explicit arguments and `depends_on` edges, locations,
  job memory/retries, no `service.uri`; 11 tests, each rule proven on a mutated copy of infra/.
  On the real infra/: `policy: 0 violations`.
- `make ci-cloud`: policy, `terraform fmt`, `validate` (both roots), `terraform test`, tflint
  (google ruleset), trivy at HIGH,CRITICAL (a public bucket grant fails it, GCP-0001). Passes
  locally with the pinned tools.
- Adapters: Cloud Storage (origin-bound sessions, keyless V4 signed downloads, idempotent
  delete), Cloud Run launcher (no retry: a second start pays Claude twice), Resend over REST with
  idempotency keys and bounded backoff. `config/cloud.toml` + `load_cloud()` hold the tunables.
- Scripts (not run): gcp-project, bootstrap-plan (reads the billing currency, F408), secrets-push,
  stripe-setup (lookup-key price, single webhook), dns (Resend + Cloudflare + verify + sending
  key), smoke (8 checks from the URL alone).
- Doc ledger: 17 entries in `infra/doc-ledger.pending.json`, Context7 or vendor page each.
- Not run: anything against Google Cloud, Stripe, Resend or Cloudflare (budget $0, no project).

### 9 Oct 2026 — STEP-08 phase A
Before: no `infra/`, no deploy workflow. After:
- `infra/policy/explicit_args.toml` (resource type → arguments that must be written, from INFRA §2),
  `locations.toml` (service → allowed locations with source; storage, Artifact Registry and Secret
  Manager rows say UNCONFIRMED: rest on D50 only), `limits.toml` (job 4 vCPU / 16 GiB / 0 retries,
  F29, L7; a third file not named in the step, added so the limit is data rather than a literal in
  the checker).
- `infra/bootstrap/`: bootstrap APIs, state bucket (versioned, `deletion_policy = "PREVENT"`), WIF
  pool `github` + provider `github-oidc` (numeric repository and owner ids, `refs/heads/main`),
  `github-deployer@` with exactly the §5 project roles, writer on the `reel` repository (cleanup:
  DELETE older than 30 days, KEEP 5 newest), 5 secret containers (no versions,
  `deletion_protection = true`), $10 monthly budget at 50/90/100 %. Local state, no backend block.
- `infra/main/`: runtime APIs, media bucket, Firestore `(default)` + 3 indexes + TTL field, 3 service
  accounts and the §5 grants, Cloud Run service and job, scheduler, `_Default` log retention,
  `/health` log exclusion. Service URL built from the project number (F61). `backend "gcs"` with
  partial config (bucket passed by deploy.yml).
- Lock files carry darwin_arm64 and linux_amd64 hashes.
- `deploy.yml`: manual trigger, `concurrency: deploy` with `cancel-in-progress: false`, plan job
  (WIF, both images for linux/amd64 tagged with the SHA, plan + JSON artifact, 20 min), apply job
  (`environment: beta`, applies the saved plan, `make smoke`, 15 min). Actions pinned by SHA (F402).
- Argument names and defaults from the provider schema dump and Context7 (F400); `validate` caught
  `all_updates_rule` needing a channel, so the budget relies on default recipients (F401).
- Optional arguments left at provider defaults on purpose: probe timings, `rpo`, `requester_pays`,
  `enable_object_retention`, Firestore index `density`/`multikey`, Cloud Run `execution_environment`,
  service-level `scaling` (revision-level `template.scaling` carries min 0 / max 2), resource-manager
  `tags`, encryption (Google-managed keys).
- Not run: `terraform plan` (no project yet), `make ci` (STEP-01), any apply. Run later (90c3a9a):
  tflint 0.64.0 0 issues (F404); the reviewer ran Trivy 0.74.0: GCP-0078 MEDIUM, GCP-0066 LOW x2,
  all by design; CI threshold HIGH,CRITICAL to be set in `make ci`.
- Senior review round 1: FAIL, 2 critical, both fixed. C1: the Cloud Run service and job now depend on
  the deployer's actAs grant (only the scheduler did). C2: `skip_wait = true` on the TTL field,
  because Google documents ten minutes or more to enable TTL and the apply job has 15. Warnings fixed:
  tfvars comment, `credit_types_treatment = "INCLUDE_ALL_CREDITS"` written, env-secret timing
  comment, deploy.yml variable comment. Round 2 pending at the time of commit.
- Review round 2 (90c3a9a): PASS, 0 critical. Fixed after it: `terraform test` with mock_provider in
  `infra/main/tests/` (IAM matrix, D62 key split, F61 URL, job limits, skip_wait; mutants with
  `skip_wait = false` and `max_retries = 1` fail it), TTL comment now names `make smoke` as the check
  (no STEP-08 task records it), `infra/.gitignore` covers tfvars and plans, bootstrap deployer
  account and roles depend on the bootstrap APIs, commit messages cite F400-F403.
- Waits for `scripts/check_policy.py`: require `depends_on` on the service, job and scheduler (not
  testable in `terraform test`); `make smoke` must check TTL ACTIVE.
- Review follow-ups (not done): confirm the three UNCONFIRMED rows in `locations.toml` and the F401
  currency rule in FACTS (the reviewer read all four pages as confirming); FACTS rows for GitHub OIDC
  claims, Scheduler OIDC, env-secret timing and TTL duration; pin secret versions for reel-api;
  `terraform test` with mock_provider as the failing-test artifact (IAM matrix, F61 URL, job limits);
  `data "google_secret_manager_secret"` so a missing container fails at plan; numeric validation on
  the GitHub id variables; image digests instead of SHA tags only; trivy threshold (GCP-0078 media
  versioning off and GCP-0066 no CMEK, both by design); check_policy.py must expand `dynamic` blocks
  and resolve `local.*` (read `terraform show -json`).
