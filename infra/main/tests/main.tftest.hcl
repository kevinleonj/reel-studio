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

  stripe_price_id  = "price_test"
  stripe_coupon_id = "coupon_test"
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

run "request_logs_keep_only_a_sample" {
  command = apply

  assert {
    condition     = strcontains(google_logging_project_exclusion.requests.filter, "logName=\"projects/test-project/logs/run.googleapis.com%2Frequests\"")
    error_message = "The exclusion must name reel-api's request log (CLOUD-COST-CAP settled 2)."
  }
  assert {
    condition     = strcontains(google_logging_project_exclusion.requests.filter, "sample(insertId, 0.99)")
    error_message = "Exclude 99 % so a 1 % sample of request logs is kept (F415)."
  }
  assert {
    condition     = !strcontains(google_logging_project_exclusion.requests.filter, "httpRequest.status")
    error_message = "Any status: a flood of 5xx answers during a spend-cap pause must not be stored in full."
  }
  assert {
    condition     = strcontains(google_logging_project_exclusion.requests.filter, "resource.labels.service_name=\"reel-api\"")
    error_message = "Only reel-api's request log is sampled, no other service's."
  }
  assert {
    condition     = google_logging_project_exclusion.requests.disabled == false
    error_message = "The exclusion must be active."
  }
}

# The env contract test (tests/unit/infra/test_env_contract.py) checks the maps in locals.tf;
# these check that each map is attached to its workload (task 2 review W5).
run "each_workload_gets_its_environment" {
  command = apply

  assert {
    condition = length(setsubtract(
      ["TIER", "FIRESTORE_PROJECT", "SITE_URL", "MAIL_FROM", "KEVIN_ALERT_EMAIL", "GCS_BUCKET", "EDITOR_JOB",
        "PAYMENTS", "STRIPE_PRICE_ID", "STRIPE_COUPON_ID", "VOICE_AVAILABLE", "WEB_DIST",
      "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_SENDING_KEY"],
      [for e in google_cloud_run_v2_service.api.template[0].containers[0].env : e.name]
    )) == 0
    error_message = "reel-api must get common_env, api_env and api_secrets (RuntimeSettings, WebSettings)."
  }
  assert {
    condition = length(setsubtract(
      ["TIER", "FIRESTORE_PROJECT", "SITE_URL", "MAIL_FROM", "KEVIN_ALERT_EMAIL", "GCS_BUCKET", "EDITOR_JOB",
      "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "RESEND_SENDING_KEY"],
      [for e in google_cloud_run_v2_job.editor.template[0].template[0].containers[0].env : e.name]
    )) == 0
    error_message = "reel-editor must get common_env and editor_secrets (RuntimeSettings, EditorSettings)."
  }
  assert {
    condition = length([
      for e in google_cloud_run_v2_job.editor.template[0].template[0].containers[0].env : e.name
      if startswith(e.name, "STRIPE_")
    ]) == 0
    error_message = "D62: the editor job never holds a Stripe value."
  }
}
