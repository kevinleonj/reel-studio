locals {
  # D50: every regional resource lives in europe-west1 (infra/policy/locations.toml).
  region = "europe-west1"
  # Cloud Storage reports bucket locations in upper case; written that way to avoid a perpetual diff.
  bucket_location = upper(local.region)

  # docs/INFRA.md §2: labels on every resource that takes them; each resource adds its `component`.
  labels = {
    app        = "reel-studio"
    env        = "beta"
    managed_by = "terraform"
  }

  # docs/INFRA.md §2: only the APIs the runtime uses.
  services = toset([
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])

  api_name       = "reel-api"
  editor_name    = "reel-editor"
  scheduler_name = "reel-scheduler"

  # F61: the service URL is known before the service exists, so SITE_URL, the bucket CORS origin and
  # the scheduler audience need no dependency on the service (never service.uri, STEP-08 task 4).
  service_url = "https://${local.api_name}-${data.google_project.this.number}.${local.region}.run.app"

  # --- reel-api (docs/INFRA.md §2, D51, F52) ---
  api_min_instances   = 0  # scale to zero: request-based billing
  api_max_instances   = 2  # cost ceiling (D51)
  api_concurrency     = 80 # requests per instance before a second one starts
  api_request_timeout = "30s"
  api_cpu             = "1"
  api_memory          = "512Mi"
  api_port            = 8080
  api_health_path     = "/health"
  api_invoker_member  = "allUsers" # public website
  api_ingress         = "INGRESS_TRAFFIC_ALL"

  # --- reel-editor (D52, F29) ---
  editor_task_count  = 1
  editor_parallelism = 1
  editor_timeout     = "3600s"
  editor_max_retries = 0 # a retry pays Claude twice
  editor_cpu         = "4"
  editor_memory      = "16Gi" # the maximum at 4 vCPU (F29, L7)

  # --- media bucket (docs/INFRA.md §2, D54, F50) ---
  media_soft_delete_seconds  = 0 # soft delete is on and billed by default (F50)
  media_short_lived_prefixes = ["in/", "work/"]
  media_short_lived_days     = 7
  media_output_prefixes      = ["out/"]
  media_output_days          = 30
  media_cors_methods         = ["GET", "HEAD", "PUT", "POST"]
  media_cors_headers         = ["Content-Type", "Content-Range", "Range", "x-goog-resumable"]
  media_cors_max_age_seconds = 3600

  # --- Firestore (D53, D55, F35) ---
  orders_collection = "orders"
  orders_indexes = {
    queue = ["status", "queue.queued_at"]
    sweep = ["status", "queue.lease_until"]
    stale = ["status", "created_at"]
  }
  orders_ttl_field = "expires_at"

  # --- sweep (D55, F26) ---
  sweep_schedule         = "*/10 * * * *"
  sweep_time_zone        = "Europe/Madrid"
  sweep_attempt_deadline = "60s"
  sweep_retry_count      = 0 # the next sweep is the retry
  sweep_path             = "/api/internal/sweep"

  log_retention_days = 30

  # docs/ARCHITECTURE.md §6: which secret each workload reads, by environment variable name.
  api_secrets = {
    STRIPE_SECRET_KEY     = "stripe-secret-key"
    STRIPE_WEBHOOK_SECRET = "stripe-webhook-secret"
    RESEND_API_KEY        = "resend-api-key"
  }
  editor_secrets = {
    ANTHROPIC_API_KEY = "anthropic-api-key"
    GEMINI_API_KEY    = "gemini-api-key"
    RESEND_API_KEY    = "resend-api-key"
  }
  # Environment secrets resolve when an instance starts: the editor job gets a new value on its next
  # execution, but warm reel-api instances keep the old one until a new revision or a restart.
  # Rotating a reel-api secret therefore also needs a redeploy (Google recommends pinned versions;
  # pinning is a follow-up in docs/handoff/cloud.md).
  secret_version = "latest"

  # Plain environment for both workloads. Names follow .env.example; GCS_BUCKET and EDITOR_JOB are
  # provisional until reel_studio/settings.py exists (STEP-01) and the env contract test checks them.
  common_env = {
    GCP_PROJECT       = var.project_id
    GCP_REGION        = local.region
    SITE_URL          = local.service_url
    PAYMENTS          = "stripe"
    EMAIL_DOMAIN      = var.email_domain
    MAIL_FROM         = var.mail_from
    KEVIN_ALERT_EMAIL = var.alert_email
    GCS_BUCKET        = google_storage_bucket.media.name
    EDITOR_JOB        = local.editor_name
  }
}
