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
    "attribute.environment"         = "assertion.environment"
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

  depends_on = [google_project_service.bootstrap]
}

# Only jobs of this repository's main branch (provider condition) that run in the beta environment,
# which Kevin approves, may act as the deployer. Every deploy.yml job that asks for a token
# declares `environment: beta`, so no job relies on how a missing claim is mapped (F411).
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.environment/${local.github_environment}"
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = google_service_account.deployer.member

  depends_on = [google_project_service.bootstrap]
}

# Project IAM admin limited to granting the roles infra/main needs: without the condition the
# deployer could grant itself roles/owner (F410). Unconditional bindings win over conditional ones,
# so this role must never also appear in deployer_project_roles (scripts/check_policy.py, iam.toml).
resource "google_project_iam_member" "deployer_iam_admin" {
  project = var.project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = google_service_account.deployer.member

  condition {
    title       = "grant-only-runtime-project-roles"
    description = "The deployer may grant only the project roles infra/main grants"
    expression  = "api.getAttribute('iam.googleapis.com/modifiedGrantsByRole', []).hasOnly([${join(", ", formatlist("'%s'", local.deployer_grantable_roles))}])"
  }

  depends_on = [google_project_service.bootstrap]
}
