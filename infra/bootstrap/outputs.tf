# Values deploy.yml needs as GitHub repository variables (not secrets: none of them grants access).

output "state_bucket" {
  description = "Bucket for Terraform state; deploy.yml passes it as -backend-config=bucket=..."
  value       = google_storage_bucket.state.name
}

output "workload_identity_provider" {
  description = "Full provider name for google-github-actions/auth workload_identity_provider."
  value       = google_iam_workload_identity_pool_provider.github_oidc.name
}

output "deployer_service_account" {
  description = "Email for google-github-actions/auth service_account."
  value       = google_service_account.deployer.email
}

output "registry" {
  description = "Docker registry path images are pushed to."
  value       = "${local.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.reel.repository_id}"
}
