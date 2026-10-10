# reel-api: one Cloud Run service for the website and the API (D51).
resource "google_cloud_run_v2_service" "api" {
  name     = local.api_name
  location = local.region
  ingress  = local.api_ingress
  # Stateless; re-created from the same image in minutes, and a stuck deletion must not block a fix.
  deletion_protection = false

  template {
    service_account = google_service_account.api.email
    # Request-based billing, scale to zero, and max instances as the cost ceiling (F52).
    scaling {
      min_instance_count = local.api_min_instances
      max_instance_count = local.api_max_instances
    }
    max_instance_request_concurrency = local.api_concurrency
    timeout                          = local.api_request_timeout

    containers {
      image = var.api_image

      ports {
        container_port = local.api_port
      }

      resources {
        limits = {
          cpu    = local.api_cpu
          memory = local.api_memory
        }
        cpu_idle          = true # CPU only while a request is in flight: request-based billing
        startup_cpu_boost = true # faster cold start of the first page load
      }

      # Probe timings left at Cloud Run's defaults; only the path is ours.
      startup_probe {
        http_get {
          path = local.api_health_path
          port = local.api_port
        }
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.api_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = local.secret_version
            }
          }
        }
      }
    }

    labels = merge(local.labels, { component = "api" })
  }

  labels = merge(local.labels, { component = "api" })

  # A revision that cannot read its secrets never becomes ready.
  # Creating a service or job that runs as an account needs actAs on it (granted in iam.tf).
  depends_on = [
    google_secret_manager_secret_iam_member.accessor,
    google_service_account_iam_member.deployer_acts_as,
    google_project_service.runtime,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = local.api_invoker_member
}

# reel-editor: one execution per order (D52).
resource "google_cloud_run_v2_job" "editor" {
  name     = local.editor_name
  location = local.region
  # Re-created from the same image; executions in flight are the app's concern, not Terraform's.
  deletion_protection = false

  template {
    task_count  = local.editor_task_count
    parallelism = local.editor_parallelism

    template {
      service_account = google_service_account.editor.email
      timeout         = local.editor_timeout
      max_retries     = local.editor_max_retries

      containers {
        image = var.editor_image

        resources {
          limits = {
            cpu    = local.editor_cpu
            memory = local.editor_memory
          }
        }

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.editor_secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = local.secret_version
              }
            }
          }
        }
      }
    }

    labels = merge(local.labels, { component = "editor" })
  }

  labels = merge(local.labels, { component = "editor" })

  # Creating a service or job that runs as an account needs actAs on it (granted in iam.tf).
  depends_on = [
    google_secret_manager_secret_iam_member.accessor,
    google_service_account_iam_member.deployer_acts_as,
    google_project_service.runtime,
  ]
}
