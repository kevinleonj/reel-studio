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
- **Deployer limits (REVIEW-FIXES CLOUD 1, done in code, not applied):** projectIamAdmin now carries
  the condition `modifiedGrantsByRole hasOnly(['roles/datastore.user'])` (F410), and only jobs in the
  `beta` environment may act as the deployer (F411). Consequence: you approve twice per deploy, once
  for the plan job and once for the apply job. Takes effect when you first apply the bootstrap root
  (never applied yet). Limits of this fix:
  - "Approved jobs only" is exactly as strong as the GitHub `beta` environment. GitHub creates a
    missing environment unprotected on first use, and nothing in CI checks it: create it with you
    as required reviewer before deploy.yml reaches main, and verify with
    `gh api repos/kevinleonj/reel-studio/environments/beta --jq .protection_rules`.
  - The condition limits which roles the deployer grants, not to whom: it could bind
    roles/datastore.user to anyone.
  - The deployer still holds strong roles: `roles/iam.serviceAccountAdmin` (setIamPolicy on any
    service account, its own included, so it could add impersonators or undo the environment gate),
    `roles/storage.admin` (reads and writes both roots' state), `roles/run.admin` plus actAs on the
    runtime accounts (runs code as reel-api and reel-editor), `roles/secretmanager.admin` (reads
    every secret; item below). None of these carries project setIamPolicy, so it cannot grant
    itself Owner, but it is not contained. ARCHITECTURE §5 and INFRA §4 now differ from the code
    (conditional projectIamAdmin, two approvals): doc edits are yours.
- **Narrower secrets role, proposal (REVIEW-FIXES CLOUD 2, not built):** the deployer holds
  `roles/secretmanager.admin` at project level, which can read every secret value. After item 1 it
  is reachable only from approved `beta` jobs, acceptable for the beta. Replacement for after the
  beta: a custom role `reelSecretIamAdmin` in the bootstrap root with exactly
  `secretmanager.secrets.get`, `secretmanager.secrets.getIamPolicy` and
  `secretmanager.secrets.setIamPolicy` (no `secretmanager.versions.access`, no create or delete:
  the containers come from bootstrap, which you apply). infra/main only adds accessor bindings on
  existing containers, so these three cover it; confirm with one plan before switching. Needs an
  ARCHITECTURE §5 edit (yours).
- **Fix c, proposal for your decision (ARCHITECTURE §5 change, not built):** a second account
  `github-planner@` bound through WIF to `attribute.environment/plan` (a `plan` environment with no
  reviewer, branches limited to main), holding only read roles: `roles/viewer` would be the simple
  choice but reads too much, so instead `roles/run.viewer`, `roles/datastore.viewer` (index and
  field metadata), `roles/storage.objectViewer` on the state bucket plus
  `roles/storage.legacyBucketReader`, `roles/iam.securityReviewer` (reads IAM policies),
  `roles/secretmanager.viewer` (metadata, no values), `roles/cloudscheduler.viewer`,
  `roles/logging.viewer`, `roles/artifactregistry.reader` and `roles/serviceusage.serviceUsageViewer`.
  The plan job would run `terraform plan -lock=false` as the planner, and only apply would need the
  deployer, so you would approve once. Open questions: whether plan can refresh every resource with
  these roles (check with one dry run), and whether images should then be built by apply instead.
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
- **First run of `make dns` to watch:** Resend record names for a subdomain may be relative to the
  domain or to the zone; `make dns` maps both to the same full name (F407 UNCONFIRMED for a
  subdomain), and the `GET /api-keys` list shape is UNCONFIRMED (an unexpected shape now stops the
  run instead of creating a duplicate key).
- **Launcher is at-most-once (review W5).** No caller may retry `launch` for one run token; on
  CloudUnavailable leave the order running and let the lease sweep fail it. Two executions with the
  same token both pass ARCHITECTURE §4's worker check, so the worker should claim the token
  atomically (set `queue.started_at` in a transaction, exit if already set). Affects the web lane's
  Dispatcher and the engine lane (the editor job starts the next order). ARCHITECTURE §3 row 86
  still reads `launch(order_id)`: docs are yours.
- **Editor image needs the cloud libraries (review W10).** `pyproject.toml` `[editor]` lacks
  google-cloud-storage, google-cloud-run and google-cloud-firestore, but the editor job uses the
  Storage and Launcher adapters. Either `[editor]` lists them or `docker/editor.Dockerfile` installs
  `[api]` too (main and engine lanes).
- **Mailer on the request path (review W7):** worst case 4 attempts x 15 s + backoff exceeds the
  30 s Cloud Run request timeout; when wiring the order-link email in reel-api, send it in the
  background or with one retry. Nothing consumes `[resend]` yet.
- **Review gate file:** the global Stop gate wants `.claude/review-verdict.json`, but
  `guard_paths.py` blocks every write to `.claude/` from a lane worktree (three reviewers hit it).
  Add the file to `lanes.json` shared paths or exempt it.

## What waits for a real project (STEP-08 tasks)
- Task 2 `make gcp-project`, task 3 `make bootstrap-plan` then your apply and the state migration,
  task 5 runs, task 6 `beta` environment and repository variables, task 7 runtime facts F30/F32/F34,
  task 8 smoke and the phone order, task 9 budget check. (Task 5's Gemini terms note is done: F409.)

## Open follow-ups (no project needed)
- `scripts/check_policy.py` false negatives (review W8): a `dynamic` block with `for_each = []`
  counts as present (e.g. a budget with no threshold rules), the `service.uri` ban is a text regex
  (misses `[0].uri`), and only direct children of `infra/` are roots. Fix by reading
  `terraform show -json` of a mocked plan.
- `make dns`: `GET /domains` ignores `has_more` (fine below 100 domains); a lost response to
  `POST /api-keys` retried could orphan a key (rare; the rerun then stops and asks for cleanup).
- cloud.toml values are key-strict but not range-checked (review S1); SigningIdentity repr shows the
  token (S2); `signed_url` signs any key: callers must authorise (S2).
- Focused review of 005d131..08a94f7: PASS, 0 critical. Its warnings are evidence gaps, to close
  next (tests only, behaviour verified by the reviewer's probes):
  - W-A: `test_failed_verification_stops_at_once` also matches the old timeout message; assert
    "marked the domain failed" and one poll, plus a failed-then-verified case.
  - W-B: the verification-timeout test lost its `clock.now >= timeout` assertion.
  - W-C: assert the original exception text is absent from CloudUnavailable, and add a launcher
    RefreshError case.
  - W-D: no test for smoke's credentials failure in `main()` or stripe-setup's SetupError path.
  - W-E: zone-relative record names are pinned only at function level; add a run through
    `run_dns` with a zone-relative fake.
  - W-F: FACTS row for `gcloud secrets describe` and
    `secrets versions list --filter=state:ENABLED --limit=1` (flags checked offline by the reviewer).
- Same review, suggestions: send `limit=100` and fail closed on `has_more` for `/domains` and
  `/api-keys`; INFRA §4 still says smoke uses `gcloud run ... describe` (docs are Kevin's); the same
  `| head -1` under pipefail exists in `scripts/ci-install.sh:57` (main lane, latent).

## Evidence lines (the gates read these)

## Log

### 10 Oct 2026 — REVIEW-FIXES.md, CLOUD items 1-5
Before: the deployer held projectIamAdmin without a condition and any main-branch job could use it;
the budget warned only after spending; each secrets run left old versions enabled; plan artifacts
lived 7 days. After (b8da8d6, 40db321, 3149d1e, ed95ab1, 567abdd), each with a failing test first:
- 1: conditional projectIamAdmin (grants only roles/datastore.user, F410), deployer bound to
  `attribute.environment/beta` with the plan job in `beta` too (F411); bootstrap `terraform test`
  (3 runs) and a check_policy rule (iam.toml) that fails on an unconditional binding. Fix c is a
  proposal under Needs Kevin.
- 2: narrower secrets role proposed under Needs Kevin (not built).
- 3: a FORECASTED_SPEND rule at 100 % beside the three current-spend rules (F412).
- 4: `make secrets-push` confirms the new version is ENABLED, then destroys older versions;
  nothing is destroyed otherwise (F413).
- 5: plan artifacts kept 1 day.
- Not applied anywhere: the bootstrap changes need your apply to take effect.

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
- Senior review of cd66765..005d131: PASS, 0 critical, 11 warnings. Fixed before push: W1 (show-once
  secrets: container checked before Stripe or Resend mints one; an existing endpoint or key with no
  stored value stops with the recovery step), W2 (record names relative to zone or domain), W3
  (unexpected list shape stops, no /verify on a verified domain, `failed` stops at once), W4
  (RetryError and google-auth errors become CloudUnavailable; messages keep only the exception type),
  W6 (TTL CREATING is pending; auth and retry errors fail one check, not the run), W9 (price
  idempotency key and endpoint URL match now pinned), W11 (F407 status, F409 Gemini terms). Open:
  W5, W7, W8, W10 under Needs Kevin / follow-ups.

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
