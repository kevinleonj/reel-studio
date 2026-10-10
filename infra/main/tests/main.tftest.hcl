# Offline test of the main root: `terraform init -backend=false && terraform test` in infra/main.
# mock_provider fakes every google call, so this runs with no project and no credentials.
# It pins what `terraform validate` cannot see: the IAM matrix (docs/ARCHITECTURE.md §5), the F61
# URL, the job limits (D52, F29) and the first-apply fixes from the senior review.

mock_provider "google" {
  mock_data "google_project" {
    defaults = {
      number = "123456789012"
    }
  }
  # The provider validates member strings even under mocks, so the computed ones must look real.
  mock_data "google_service_account" {
    defaults = {
      email  = "github-deployer@test-project.iam.gserviceaccount.com"
      member = "serviceAccount:github-deployer@test-project.iam.gserviceaccount.com"
      name   = "projects/test-project/serviceAccounts/github-deployer@test-project.iam.gserviceaccount.com"
    }
  }
  mock_resource "google_service_account" {
    defaults = {
      email  = "runtime@test-project.iam.gserviceaccount.com"
      member = "serviceAccount:runtime@test-project.iam.gserviceaccount.com"
      name   = "projects/test-project/serviceAccounts/runtime@test-project.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id   = "test-project"
  api_image    = "registry.test/reel-api:abc"
  editor_image = "registry.test/reel-editor:abc"
  email_domain = "mail.test"
  mail_from    = "Reel Studio <reels@mail.test>"
  alert_email  = "alerts@mail.test"
}

run "service_url_from_project_number" {
  command = apply

  assert {
    condition     = output.service_url == "https://reel-api-123456789012.europe-west1.run.app"
    error_message = "The service URL must be built from the project number (F61), never from service.uri."
  }
  assert {
    condition     = google_cloud_scheduler_job.sweep.http_target[0].oidc_token[0].audience == output.service_url
    error_message = "The scheduler's OIDC audience must be the service URL reel-api checks."
  }
  assert {
    condition     = length(google_storage_bucket.media.cors) == 1 && tolist(google_storage_bucket.media.cors[0].origin) == tolist([output.service_url])
    error_message = "Bucket CORS must allow only the service origin (F32)."
  }
}

run "iam_matrix" {
  command = apply

  assert {
    condition     = length(google_secret_manager_secret_iam_member.accessor) == 6
    error_message = "Three secrets for reel-api and three for reel-editor (docs/ARCHITECTURE.md §6)."
  }
  assert {
    condition = alltrue([
      for key, grant in google_secret_manager_secret_iam_member.accessor :
      !(startswith(key, "api-") && contains(["anthropic-api-key", "gemini-api-key"], grant.secret_id))
    ])
    error_message = "D62: the website service never holds the Anthropic or Gemini key."
  }
  assert {
    condition     = length(google_service_account_iam_member.deployer_acts_as) == 3
    error_message = "The deployer acts as exactly the three runtime accounts."
  }
  assert {
    condition     = length(google_cloud_run_v2_job_iam_member.editor_executor) == 2
    error_message = "reel-api and reel-editor may start the editor job with overrides (F30)."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.public.member == "allUsers" && google_cloud_run_v2_service_iam_member.public.role == "roles/run.invoker"
    error_message = "The website is public through run.invoker only."
  }
}

run "editor_job_limits" {
  command = apply

  assert {
    condition     = google_cloud_run_v2_job.editor.template[0].template[0].max_retries == 0
    error_message = "D52: a retry pays Claude twice."
  }
  assert {
    condition     = google_cloud_run_v2_job.editor.template[0].template[0].containers[0].resources[0].limits["cpu"] == "4" && google_cloud_run_v2_job.editor.template[0].template[0].containers[0].resources[0].limits["memory"] == "16Gi"
    error_message = "D52, F29, L7: 4 vCPU and 16 GiB, the maximum at 4 vCPU."
  }
  assert {
    condition     = google_cloud_run_v2_job.editor.template[0].template[0].timeout == "3600s"
    error_message = "D52: 60-minute task timeout."
  }
  assert {
    condition     = google_cloud_run_v2_service.api.template[0].scaling[0].max_instance_count == 2 && google_cloud_run_v2_service.api.template[0].scaling[0].min_instance_count == 0
    error_message = "D51: reel-api scales from 0 to at most 2 instances."
  }
}

run "ttl_does_not_block_the_apply" {
  command = apply

  assert {
    condition     = google_firestore_field.orders_ttl.skip_wait == true
    error_message = "Enabling TTL takes ten minutes or more; waiting would outlive the 15-minute apply job."
  }
}
