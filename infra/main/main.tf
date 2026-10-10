data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_service" "runtime" {
  for_each = local.services

  service = each.value
  # Bootstrap enables some of the same APIs; turning one off on destroy would break that root.
  disable_on_destroy         = false
  disable_dependent_services = false
}

# Uploads (in/), intermediate files (work/) and finished Reels (out/) for every order (D54).
resource "google_storage_bucket" "media" {
  name          = "${var.project_id}-media"
  location      = local.bucket_location
  storage_class = "STANDARD" # files live days, not months; colder classes add retrieval fees
  # IAM only, never public: downloads use V4 signed URLs, uploads use resumable sessions (F32, F34).
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  # Soft delete is on and billed by default (F50); order files are disposable by design.
  soft_delete_policy {
    retention_duration_seconds = local.media_soft_delete_seconds
  }
  # Objects are written once per order step; old versions would only cost money.
  versioning {
    enabled = false
  }
  force_destroy = false
  # Users' clips and Reels: deleting the bucket must be a deliberate edit.
  deletion_policy = "PREVENT"

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age            = local.media_short_lived_days
      matches_prefix = local.media_short_lived_prefixes
    }
  }
  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age            = local.media_output_days
      matches_prefix = local.media_output_prefixes
    }
  }

  # Browser uploads to resumable sessions and playback of the finished Reel, from our origin only (F32).
  cors {
    origin          = [local.service_url]
    method          = local.media_cors_methods
    response_header = local.media_cors_headers
    max_age_seconds = local.media_cors_max_age_seconds
  }

  labels = merge(local.labels, { component = "media" })

  depends_on = [google_project_service.runtime]
}
