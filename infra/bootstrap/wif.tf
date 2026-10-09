# Workload Identity Federation: GitHub Actions on main of this repository becomes github-deployer@
# without a key file (docs/INFRA.md §2 bootstrap extras, docs/ARCHITECTURE.md §5).

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "Deploys from the reel-studio repository"
  disabled                  = false

  depends_on = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool_provider" "github_oidc" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  description                        = "Tokens from the main branch of one repository only"
  disabled                           = false

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }
  # Numeric ids, not names: a renamed or re-created repository with the same name cannot deploy.
  attribute_condition = join(" && ", [
    "assertion.repository_id == \"${var.github_repository_id}\"",
    "assertion.repository_owner_id == \"${var.github_repository_owner_id}\"",
    "assertion.ref == \"refs/heads/main\"",
  ])

  oidc {
    issuer_uri = local.github_oidc_issuer
    # allowed_audiences left empty: the audience must then be this provider's resource name, which is
    # what google-github-actions/auth sends by default.
  }
}

resource "google_service_account" "deployer" {
  account_id   = "github-deployer"
  display_name = "GitHub deployer"
  description  = "Applies infra/main from deploy.yml after a manual approval"
  disabled     = false
}

# Only identities from the provider above whose repository id matches may act as the deployer.
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = google_service_account.deployer.member
}
