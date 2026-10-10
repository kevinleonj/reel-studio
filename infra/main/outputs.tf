output "service_url" {
  description = "Deterministic reel-api URL (F61); deploy.yml passes it to make smoke."
  value       = local.service_url
}

output "media_bucket" {
  description = "Bucket for in/, work/ and out/."
  value       = google_storage_bucket.media.name
}

output "editor_job" {
  description = "Cloud Run job reel-api starts once per order."
  value       = google_cloud_run_v2_job.editor.name
}
