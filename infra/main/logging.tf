# Log buckets and exclusions take no labels.
resource "google_logging_project_bucket_config" "default" {
  project        = var.project_id
  location       = "global" # _Default is a global bucket
  bucket_id      = "_Default"
  retention_days = local.log_retention_days
  # Written out so nobody locks retention or turns on Log Analytics (which cannot be undone) by accident.
  locked           = false
  enable_analytics = false

  depends_on = [google_project_service.runtime]
}

# Request logs for /health (smoke tests, uptime checks) are noise (docs/INFRA.md §2).
resource "google_logging_project_exclusion" "health" {
  name     = "reel-api-health"
  disabled = false
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${local.api_name}\"",
    "logName=\"projects/${var.project_id}/logs/run.googleapis.com%2Frequests\"",
    "httpRequest.requestUrl=~\"${local.api_health_path}$\"",
  ])

  depends_on = [google_project_service.runtime]
}

# Every request writes a request log entry, 429s and 5xx included, and Cloud Logging is not eligible
# for spend caps (F414): storage past 50 GiB a month is $0.50 per GiB (F415). Keep a 1 % sample of
# reel-api's request log, any status: what Cloud Run answers while a spend cap pauses it is not
# documented, and a flood of 5xx answers would otherwise be stored in full.
resource "google_logging_project_exclusion" "requests" {
  name        = "reel-api-requests-sampled"
  description = "Keep a sample of reel-api request logs; application logs stay complete"
  disabled    = false
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${local.api_name}\"",
    "logName=\"projects/${var.project_id}/logs/run.googleapis.com%2Frequests\"",
    "sample(insertId, ${1 - local.request_log_keep_fraction})",
  ])

  depends_on = [google_project_service.runtime]
}
