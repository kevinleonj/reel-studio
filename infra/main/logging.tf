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
