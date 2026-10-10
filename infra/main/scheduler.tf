# Frees dead leases and missed expiries every 10 minutes (D55). europe-west1: not offered in Madrid (F26).
# Cloud Scheduler jobs take no labels.
resource "google_cloud_scheduler_job" "sweep" {
  name             = "reel-sweep"
  region           = local.region
  schedule         = local.sweep_schedule
  time_zone        = local.sweep_time_zone
  attempt_deadline = local.sweep_attempt_deadline
  paused           = false

  retry_config {
    retry_count = local.sweep_retry_count
  }

  http_target {
    http_method = "POST"
    uri         = "${local.service_url}${local.sweep_path}"
    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = local.service_url
    }
  }

  depends_on = [google_project_service.runtime, google_service_account_iam_member.deployer_acts_as]
}
