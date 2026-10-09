# Identities and grants: exactly docs/ARCHITECTURE.md §5, nothing broader.

resource "google_service_account" "api" {
  account_id   = local.api_name
  display_name = "Reel API"
  description  = "Website and API: orders, uploads, starting editor jobs, signed links"
  disabled     = false
}

resource "google_service_account" "editor" {
  account_id   = local.editor_name
  display_name = "Reel editor"
  description  = "Edits one order per job execution"
  disabled     = false
}

# No roles on resources: reel-api checks its OIDC token (audience = service URL, email = this account).
resource "google_service_account" "scheduler" {
  account_id   = local.scheduler_name
  display_name = "Reel scheduler"
  description  = "Calls the sweep endpoint every 10 minutes"
  disabled     = false
}

locals {
  runtime_accounts = {
    api       = google_service_account.api
    editor    = google_service_account.editor
    scheduler = google_service_account.scheduler
  }
  workers = {
    api    = google_service_account.api
    editor = google_service_account.editor
  }
  secret_grants = merge(
    { for env, secret in local.api_secrets : "api-${secret}" => { secret = secret, member = google_service_account.api.member } },
    { for env, secret in local.editor_secrets : "editor-${secret}" => { secret = secret, member = google_service_account.editor.member } },
  )
}

resource "google_project_iam_member" "datastore_user" {
  for_each = local.workers

  project = var.project_id
  role    = "roles/datastore.user"
  member  = each.value.member
}

resource "google_storage_bucket_iam_member" "media_object_admin" {
  for_each = local.workers

  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = each.value.member
}

# Narrowest role that can run a job with overrides (F30, L4).
resource "google_cloud_run_v2_job_iam_member" "editor_executor" {
  for_each = local.workers

  project  = var.project_id
  location = google_cloud_run_v2_job.editor.location
  name     = google_cloud_run_v2_job.editor.name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = each.value.member
}

# Signing download URLs without a key file (F34: conflicting sources; STEP-08 task 7 proves it).
resource "google_service_account_iam_member" "api_signs_as_itself" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = google_service_account.api.member
}

# Secret containers come from the bootstrap root; values never pass through Terraform.
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.secret_grants

  project   = var.project_id
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}

# docs/ARCHITECTURE.md §5 lists this under the bootstrap root, but the accounts are created here
# (docs/INFRA.md §2), so the grant lives here with the same scope: the deployer may act as each
# runtime account to deploy the service, the job and the scheduler. Recorded under "Needs Kevin".
data "google_service_account" "deployer" {
  account_id = "github-deployer"
}

resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each = local.runtime_accounts

  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountUser"
  member             = data.google_service_account.deployer.member
}
