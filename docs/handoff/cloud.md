# Handoff — lane cloud

Written by the cloud lane only. Newest entry on top.

## Status board
- Done: STEP-08 phase A — policy data (`infra/policy/`), Terraform `infra/bootstrap/` and `infra/main/`
  (fmt, init `-backend=false` and validate pass on Terraform 1.16.5 with provider 8.6.0),
  `.github/workflows/deploy.yml`. Committed locally on `step-08-cloud`, not pushed.
- Partly: STEP-08 task 1 (policy files exist; `scripts/check_policy.py`, its bad fixtures and the
  `ci-install.d/cloud.sh` tools wait for STEP-01).
- Blocked: push and pull request, until STEP-01 is merged to main (Kevin's instruction).
- Not started: tasks 0, 2, 3 (plan/apply), 5, 7, 8, 9.
- Next: after STEP-01 merges — `git merge origin/main`, then `scripts/check_policy.py` test first,
  `mk/cloud.mk`, `scripts/ci-install.d/cloud.sh`, tflint config, `make ci`, push.

## Needs Kevin
- **Where the deployer's `roles/iam.serviceAccountUser` lives.** `docs/ARCHITECTURE.md` §5 says the
  bootstrap root grants it on the three runtime accounts; `docs/INFRA.md` §2 creates those accounts in
  the main root, so they do not exist when bootstrap is applied. I put the grant in
  `infra/main/iam.tf` with the same scope (one binding per runtime account, nothing at project
  level). The deployer already holds `roles/iam.serviceAccountAdmin`, so no privilege changes. If
  you prefer the accounts created in bootstrap instead, say so and I move both.
- **Upgrade Terraform on the Mac to 1.16.5** (`brew upgrade terraform`; Homebrew has 1.16.1). Both
  roots pin `required_version = "= 1.16.5"` (D60). This session used a checksum-verified 1.16.5 in the
  session scratchpad (F403).
- **Bootstrap variables you choose at plan time** (no defaults): `project_id`, `billing_account`,
  `budget_currency_code` (your billing account's currency, F401), `github_repository_id`,
  `github_repository_owner_id`. **Main root**, as GitHub repository variables: `GCP_PROJECT_ID`,
  `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SA`, `TF_STATE_BUCKET` (bootstrap outputs),
  `EMAIL_DOMAIN`, `MAIL_FROM`, `KEVIN_ALERT_EMAIL`.
- **Create the `beta` environment before deploy.yml reaches main** (task 6): you as required
  reviewer, deployment branches limited to main. GitHub auto-creates a missing environment without
  protection, so the first dispatch would apply unreviewed. Today `gh api` shows 0 environments.
- **`.gitignore` lacks `*.tfvars`, `*.tfvars.json`, `tfplan.json`, `crash.log`** (outside the cloud
  lane). The repository is public; until added, pass bootstrap values with `-var` only.
- **A hook auto-commits every Write/Edit as `chore(auto): ...`.** It skipped files the hardcode hooks
  flagged, leaving a half-committed tree. I squashed the 14+ auto-commits into logical commits
  (local only, never pushed). Worth turning off for lane worktrees.
- **Global hardcode hooks flag the Terraform constants files** (`infra/*/locals.tf`: API service names,
  secret container names read as "SECRET"/"MODEL ID", GitHub's OIDC issuer, the F61 URL template).
  These values already sit in the root's named-constant file; there is no suppression marker for
  `gate-hardcode.sh`. Left as is; your call whether `.tf` locals files should be exempt.

## What waits for STEP-01 (not on main yet)
- `scripts/check_policy.py` + failing tests on bad fixtures in `tests/unit/infra/` (needs pytest and
  `pyproject.toml`). It reads `infra/policy/explicit_args.toml`, `locations.toml` and `limits.toml`.
- `mk/cloud.mk` targets (`bootstrap-plan`, `gcp-project`, `smoke`, `secrets-push`, `dns`,
  `stripe-setup`) and wiring `terraform fmt/validate`, tflint, trivy and the policy check into `make ci`.
- `scripts/ci-install.d/cloud.sh`: Terraform 1.16.5, tflint, Trivy at pinned versions.
- Env names in `infra/main/locals.tf` `common_env`: `GCS_BUCKET` and `EDITOR_JOB` are provisional until
  `reel_studio/settings.py` exists; the env contract test will reconcile them.
- `deploy.yml` also needs `docker/api.Dockerfile` (web lane) and `docker/editor.Dockerfile` (engine lane),
  the `beta` environment with you as reviewer (`gh api`, task 6), and `make smoke` (`scripts/smoke.py`).

## Evidence lines (the gates read these)

## Log

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
- Not run: `terraform plan` (no project yet), tflint, trivy, `make ci` (STEP-01), any apply.
- Senior review round 1: FAIL, 2 critical, both fixed. C1: the Cloud Run service and job now depend on
  the deployer's actAs grant (only the scheduler did). C2: `skip_wait = true` on the TTL field,
  because Google documents ten minutes or more to enable TTL and the apply job has 15. Warnings fixed:
  tfvars comment, `credit_types_treatment = "INCLUDE_ALL_CREDITS"` written, env-secret timing
  comment, deploy.yml variable comment. Round 2 pending at the time of commit.
- Review follow-ups (not done): confirm the three UNCONFIRMED rows in `locations.toml` and the F401
  currency rule in FACTS (the reviewer read all four pages as confirming); FACTS rows for GitHub OIDC
  claims, Scheduler OIDC, env-secret timing and TTL duration; pin secret versions for reel-api;
  `terraform test` with mock_provider as the failing-test artifact (IAM matrix, F61 URL, job limits);
  `data "google_secret_manager_secret"` so a missing container fails at plan; numeric validation on
  the GitHub id variables; image digests instead of SHA tags only; trivy threshold (GCP-0078 media
  versioning off and GCP-0066 no CMEK, both by design); check_policy.py must expand `dynamic` blocks
  and resolve `local.*` (read `terraform show -json`).
