resource "google_project_service" "bootstrap" {
  for_each = local.bootstrap_services

  service = each.value
  # Turning an API off on destroy would break the main root, which shares the project.
  disable_on_destroy         = false
  disable_dependent_services = false
}

# Terraform state for both roots: bootstrap after its migration, main under the "main" prefix.
resource "google_storage_bucket" "state" {
  name          = "${var.project_id}-tfstate"
  location      = local.bucket_location
  storage_class = "STANDARD" # the only class without retrieval fees; state is read on every plan
  # IAM only, no object ACLs, never public (docs/INFRA.md §2 bootstrap extras).
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  # Every state write keeps the previous version, so a bad apply can be rolled back by hand.
  versioning {
    enabled = true
  }
  # The 7-day default stays on here (unlike the media bucket) as a second safety net for state.
  soft_delete_policy {
    retention_duration_seconds = local.state_soft_delete_seconds
  }
  force_destroy = false
  # A destroy of the bucket that holds all state must be a deliberate edit, never a side effect.
  deletion_policy = "PREVENT"

  labels = merge(local.labels, { component = "tfstate" })

  depends_on = [google_project_service.bootstrap]
}
