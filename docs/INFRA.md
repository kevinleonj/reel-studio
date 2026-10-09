# INFRA — Google Cloud, Terraform, CI/CD, cost

Locked with `docs/DECISIONS.md` v1. Region `europe-west1` (D50). Terraform 1.16.5,
`hashicorp/google ~> 8.6` (F36). Every cost- or security-relevant argument is written out, even when
it equals the default, with a one-line comment saying why. Look up every argument name with Context7
(`/hashicorp/terraform-provider-google`) before writing it; record anything new in `docs/FACTS.md`.

## 1. Two Terraform roots

| Root | Holds | Applied by | State |
|---|---|---|---|
| `infra/bootstrap/` | Project services needed by Terraform itself, the state bucket, Workload Identity pool and provider, `github-deployer@` and its roles, the budget, the Artifact Registry repository and the 5 secret containers (no values) | Kevin, once, from his laptop (`make bootstrap-plan`, then he runs the printed apply command himself; Claude Code is denied `terraform apply`) | Local file, then migrated into the state bucket |
| `infra/main/` | Everything else in the table below | GitHub `deploy.yml` only, after a manual approval | `gs://<state bucket>/main` |

Order of the first deploy: bootstrap (Kevin applies) → `make secrets-push` → `make stripe-setup` and
`make dns` (they write their own secrets) → `deploy.yml`. Images can be pushed only after bootstrap.

The website's address is known before it exists: `https://reel-api-<project number>.europe-west1.run.app`
(F61). Terraform builds it from `data.google_project.number` and uses it for `SITE_URL`, the bucket CORS
origin, the Stripe URLs, the upload origin and the scheduler's OIDC audience, so there is no cycle.

Project: `reel-studio-beta` plus a short suffix, created by Claude Code in step 8 with Kevin's `gcloud`
login (billing account ID from `.env` `GCP_BILLING_ACCOUNT`).

## 2. Resources (main root)

| Resource | Arguments set on purpose | Why |
|---|---|---|
| `google_project_service` | run, firestore, storage, artifactregistry, secretmanager, cloudscheduler, iam, iamcredentials, logging; `disable_on_destroy = false` | Only what we use |
| `google_artifact_registry_repository.reel` (bootstrap root) | `format = "DOCKER"`, `location = europe-west1`, cleanup: DELETE any tag state older than 30 days, KEEP the 5 most recent versions (keep wins), `cleanup_policy_dry_run = false` | Storage after 0.5 GiB is billed; every image is tagged with its commit, so a delete-untagged rule alone deletes nothing |
| `google_storage_bucket.media` | `location = "EUROPE-WEST1"`, `storage_class = "STANDARD"`, `uniform_bucket_level_access = true`, `public_access_prevention = "enforced"`, `soft_delete_policy { retention_duration_seconds = 0 }`, lifecycle delete: age 7 for `in/` and `work/`, age 30 for `out/`, CORS: origin = the service URL (F61), methods GET HEAD PUT POST, headers Content-Type Content-Range Range x-goog-resumable, max age 3600; `force_destroy = false`; `versioning` off | Soft delete is on and billed by default (F50); browser uploads and playback |
| `google_firestore_database` `(default)` | `location_id = "europe-west1"`, `type = "FIRESTORE_NATIVE"`, `database_edition = "STANDARD"`, `point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_DISABLED"`, `delete_protection_state = "DELETE_PROTECTION_ENABLED"`, `deletion_policy = "ABANDON"` | Free quota only on `(default)` (F35); orders are short-lived, so no recovery cost |
| `google_firestore_index` × 3 | `(status, queue.queued_at)`, `(status, queue.lease_until)`, `(status, created_at)` on `orders` | Queue, sweep, missed expiries |
| `google_firestore_field` | TTL on `orders.expires_at` | Records disappear after 30 days |
| `google_secret_manager_secret` × 5 (bootstrap root) | `anthropic-api-key`, `gemini-api-key`, `resend-api-key`, `stripe-secret-key`, `stripe-webhook-secret`; `replication { user_managed { replicas { location = "europe-west1" } } }`; no versions in Terraform | Values never enter state |
| `google_service_account` × 3 | `reel-api`, `reel-editor`, `reel-scheduler` | One identity per workload |
| IAM members | Exactly the table in `docs/ARCHITECTURE.md` §5 | Least privilege |
| `google_cloud_run_v2_service.api` | `ingress = "INGRESS_TRAFFIC_ALL"`, `deletion_protection = false`, `service_account`, `scaling { min_instance_count = 0, max_instance_count = 2 }`, `max_instance_request_concurrency = 80`, `timeout = "30s"`, container `resources { limits = { cpu = "1", memory = "512Mi" }, cpu_idle = true, startup_cpu_boost = true }`, port 8080, startup probe `GET /health`, env from config, secrets by reference | Request-based billing, scale to zero, cost ceiling (F52) |
| `google_cloud_run_v2_service_iam_member` | `allUsers` → `roles/run.invoker` | Public website |
| `google_cloud_run_v2_job.editor` | `deletion_protection = false`, `task_count = 1`, `parallelism = 1`, task `timeout = "3600s"`, `max_retries = 0`, `service_account`, `resources { limits = { cpu = "4", memory = "16Gi" } }`, env from config, secrets by reference | A retry pays Claude twice; 16 GiB is the maximum at 4 vCPU (F29) |
| `google_cloud_scheduler_job.sweep` | `region = "europe-west1"`, `schedule = "*/10 * * * *"`, `time_zone = "Europe/Madrid"`, `attempt_deadline = "60s"`, `retry_config { retry_count = 0 }`, `http_target { http_method = "POST", uri = "<api>/api/internal/sweep", oidc_token { service_account_email = reel-scheduler, audience = "<api>" } }` | Not offered in Madrid (F26); the next sweep is the retry |
| `google_logging_project_bucket_config` `_Default` | `retention_days = 30` | Explicit |
| `google_logging_project_exclusion` | Cloud Run request logs for `/health` (needs `roles/logging.configWriter`) | Noise |
| Labels on every resource that takes them | `app = "reel-studio"`, `env = "beta"`, `component`, `managed_by = "terraform"` | Cost reports by component |

Bootstrap root extras: state bucket (`versioning = true`, uniform access, public access prevention,
soft delete left at its 7-day default as an extra safety net for state); Workload Identity pool
`github` and provider `github-oidc` with `attribute_condition` on the numeric `repository_id`,
`repository_owner_id` and `ref == "refs/heads/main"`; `github-deployer@` with the roles in
`docs/ARCHITECTURE.md` §5; `google_billing_budget` with `calendar_period = "MONTH"`, amount 10 in the
billing account's currency, thresholds 0.5, 0.9, 1.0, emails to billing admins.

## 3. Things done by API, not by hand (Kevin's rule)

| Task | Command | Uses |
|---|---|---|
| Create the project, link billing | `make gcp-project` | Kevin's `gcloud` login |
| Push secret values | `make secrets-push` (copies `CLOUD_ANTHROPIC_API_KEY`, `CLOUD_GEMINI_API_KEY`, `STRIPE_SECRET_KEY`; never prints) | Kevin's `gcloud` login |
| Resend domain + DNS | `make dns`: create `reels.limeralda.com` in Resend (region eu-west-1), add the returned records in Cloudflare as DNS-only, wait for Resend to verify, create a sending-only key for that domain and write it straight to Secret Manager | `RESEND_API_KEY` (full access, laptop only), `CLOUDFLARE_API_TOKEN` (DNS edit on limeralda.com) |
| Stripe price and webhook endpoint | `make stripe-setup MODE=test|live`: product "Reel", price €19 one-time, webhook endpoint for the two events; the endpoint's signing secret goes straight to Secret Manager | `STRIPE_SECRET_KEY` |
| Promotion codes for friends | `reelctl codes create --name <friend> --expires <YYYY-MM-DD>` (100% off, `max_redemptions` from `config/limits.toml` `[codes]`, a ceiling only) | `STRIPE_SECRET_KEY` |
| Anthropic workspace spend limit ($100) | Kevin, in the Claude Console (an Admin API route for limits was not checked; use it if one exists) | — |

## 4. CI and deploy (GitHub Actions, free on a public repo, F48)

`ci.yml`, on every push and pull request:
- `concurrency: ci-${{ github.ref }}`, `cancel-in-progress: true`; `timeout-minutes: 20`;
  `permissions: contents: read`; `runs-on: ubuntu-24.04` (standard runner only; a pinned image name, not `latest`).
- One job: `scripts/ci-install.sh` (uv, Node 24, Debian ffmpeg, the gitleaks binary, then each lane's `scripts/ci-install.d/*.sh`;
  STEP-08 adds Terraform 1.16.5, tflint and Trivy), then `make ci`. The same target runs on the laptop.

`make ci` runs, in order: `ruff format --check`, `ruff check`, `mypy` on `reel_studio`, `pytest -m "not paid"`,
web `npm ci`, `eslint`, `astro check`, `vitest`, `astro build`,
`gitleaks detect`, `terraform fmt -check -recursive`, `terraform validate` (both roots, `-backend=false`),
`tflint`, `trivy config infra/`, the explicit-arguments policy check, the hard-coded value scan (`scripts/check_literals.py`, D76),
the hook self-check, the gates self-test,
and the env contract test (every variable the code reads is set in Terraform or `.env.example`).
On success, and only with a clean working tree, it writes `.ci-pass` containing `git rev-parse HEAD`
(the push hook checks it). Lighthouse and the Playwright suite run in `make prerelease`, by hand before
STEP-08 and STEP-09, not on every push.

The `main` branch has a GitHub ruleset (set by STEP-01 through `gh api`): pull request required, the CI
check must pass, no force-push, no deletion.

`deploy.yml`, manual trigger only:
- Job **plan**: Workload Identity login, build both images for `linux/amd64`, push with the commit SHA
  as tag, `terraform plan -out tfplan`, `terraform show -json tfplan` uploaded as an artifact. 20 min.
- Job **apply**: `environment: beta` with Kevin as required reviewer, applies that exact plan, then
  runs `make smoke URL=<service url>`. 15 min. `concurrency: deploy`, `cancel-in-progress: false`.
- `make smoke` (outside-in): `GET /health` is 200; `GET /` contains the app root; `GET /api/config` is
  JSON; the live service has `cpu_idle = true` and max instances 2; the job has timeout 3600 s and
  0 retries (read with `gcloud run ... describe`). Any failure marks the deploy red.

## 5. Cost (FinOps: inform, optimise, operate)

Per Reel, inputs marked M (measured), F (fact), A (assumption):

| Line | Arithmetic | USD per Reel |
|---|---|---|
| Claude (Sonnet 5.5) | Measured on the old kit: $0.95 (M, F53). Target for our loop ≤ $1.20 (A3). 40-file orders estimated at $2 (A). Hard cap $5 (D37) | 0.95 to 2.00, never above 5.00 |
| Gemini transcription (voice on) | Speech minutes × $0.005 (F37); 5 min of speech plus the re-check of 1 min → 6 × 0.005 | 0.03 |
| Editor job compute | 4 vCPU × 600 s × $0.000018 + 16 GiB × 600 s × $0.000002 (F49, duration A1) = 0.0432 + 0.0192 | 0.06 before the free tier |
| Website, Firestore, emails | Inside free tiers at beta volume (F35, F25) | about 0 |
| Storage and download traffic | Not priced here; read it from the billing report after 10 orders | measure |

Per month:

| Volume | Claude | Editor compute after free tier (240,000 vCPU-s, 450,000 GiB-s, F49) |
|---|---|---|
| About 105 Reels (what $100 buys at $0.95) | $100, then the workspace limit stops it (D59) | CPU 252,000 − 240,000 = 12,000 × 0.000018 = $0.22; memory 1,008,000 − 450,000 = 558,000 × 0.000002 = $1.12; total $1.33 |
| 217 Reels (50 a week × 4.345) | $206 at $0.95, but capped at $100 | CPU 520,800 − 240,000 = 280,800 × 0.000018 = $5.05; memory 2,083,200 − 450,000 = 1,633,200 × 0.000002 = $3.27; total $8.32 |

The Cloud Run free tier is per billing account: if Kevin's other projects on the same billing account
use it, these lines grow. Always-on cost: Artifact Registry beyond 0.5 GiB (about $0.10 per GiB-month);
5 secret versions; 1 scheduler job. Target: under $1 a month at rest.

Levers, largest first: (1) caching stays on and stable (forgetting it costs about 4× on Claude);
(2) contact sheets instead of single frames; (3) Haiku drop-files pass, only if the A/B allows;
(4) effort `medium`, only if the A/B allows; (5) job memory down to what step 8 measures.

Hard stops: Anthropic workspace limit $100 a month (D59); $5 per Reel (D37); 2 running jobs and
50 Reels a week (D55); API max 2 instances (D51). Warning only: the $10 Google Cloud budget alert.
