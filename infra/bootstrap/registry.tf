# Images for reel-api and reel-editor, tagged with the commit SHA by deploy.yml.
resource "google_artifact_registry_repository" "reel" {
  repository_id = "reel"
  location      = local.region
  format        = "DOCKER"
  mode          = "STANDARD_REPOSITORY"
  description   = "reel-api and reel-editor images"

  # Storage beyond 0.5 GiB is billed. Every image carries a commit tag, so a delete-untagged rule alone
  # would delete nothing (docs/INFRA.md §2). KEEP wins over DELETE, so the 5 newest always survive.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "delete-older-than-30-days"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = local.image_max_age
    }
  }
  cleanup_policies {
    id     = "keep-5-most-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = local.image_keep_recent
    }
  }

  labels = merge(local.labels, { component = "registry" })

  depends_on = [google_project_service.bootstrap]
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  location   = google_artifact_registry_repository.reel.location
  repository = google_artifact_registry_repository.reel.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deployer.member
}
