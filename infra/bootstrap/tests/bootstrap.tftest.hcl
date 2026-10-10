# Offline test of the bootstrap root: `terraform init -backend=false && terraform test` here.
# mock_provider fakes every google call: no project, no credentials, no apply.
# Pins the deployer's limits (REVIEW-FIXES CLOUD item 1) and the budget's early warning (item 3).

mock_provider "google" {
  mock_data "google_project" {
    defaults = {
      number = "123456789012"
    }
  }
  # The provider validates member strings even under mocks, so the computed ones must look real.
  mock_resource "google_service_account" {
    defaults = {
      email  = "github-deployer@test-project.iam.gserviceaccount.com"
      member = "serviceAccount:github-deployer@test-project.iam.gserviceaccount.com"
      name   = "projects/test-project/serviceAccounts/github-deployer@test-project.iam.gserviceaccount.com"
    }
  }
  mock_resource "google_iam_workload_identity_pool" {
    defaults = {
      name = "projects/123456789012/locations/global/workloadIdentityPools/github"
    }
  }
}

variables {
  project_id                 = "test-project"
  billing_account            = "000000-000000-000000"
  budget_currency_code       = "EUR"
  github_repository_id       = "111"
  github_repository_owner_id = "222"
}

run "deployer_cannot_grant_itself_owner" {
  command = apply

  assert {
    condition     = !contains(keys(google_project_iam_member.deployer), "roles/resourcemanager.projectIamAdmin")
    error_message = "An unconditional projectIamAdmin binding would override the conditional one."
  }
  assert {
    condition     = google_project_iam_member.deployer_iam_admin.role == "roles/resourcemanager.projectIamAdmin"
    error_message = "The deployer keeps projectIamAdmin, but only with a condition."
  }
  assert {
    condition     = google_project_iam_member.deployer_iam_admin.condition[0].expression == "api.getAttribute('iam.googleapis.com/modifiedGrantsByRole', []).hasOnly(['roles/datastore.user'])"
    error_message = "The deployer may grant only roles/datastore.user (the one project role infra/main grants)."
  }
}

run "only_approved_jobs_become_the_deployer" {
  command = apply

  assert {
    condition     = google_iam_workload_identity_pool_provider.github_oidc.attribute_mapping["attribute.environment"] == "assertion.environment"
    error_message = "The provider must map GitHub's environment claim."
  }
  assert {
    condition     = google_service_account_iam_member.deployer_wif.member == "principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github/attribute.environment/beta"
    error_message = "Only jobs in the beta environment (Kevin approves) may act as the deployer."
  }
}

run "budget_warns_before_the_money_is_spent" {
  command = apply

  assert {
    condition     = length([for rule in google_billing_budget.monthly.threshold_rules : rule if rule.spend_basis == "FORECASTED_SPEND"]) == 1
    error_message = "One rule must fire on the forecast, before the spend happens (REVIEW-FIXES CLOUD 3)."
  }
  assert {
    condition     = length([for rule in google_billing_budget.monthly.threshold_rules : rule if rule.spend_basis == "CURRENT_SPEND"]) == 3
    error_message = "The 50/90/100 % rules on actual spend stay (D59)."
  }
}
