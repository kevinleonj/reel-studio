locals {
  # D50: every regional resource lives in europe-west1 (infra/policy/locations.toml).
  region = "europe-west1"
  # Cloud Storage reports bucket locations in upper case; written that way to avoid a perpetual diff.
  bucket_location = upper(local.region)

  # docs/INFRA.md §2: labels on every resource that takes them; each resource adds its `component`.
  labels = {
    app        = "reel-studio"
    env        = "beta"
    managed_by = "terraform"
  }

  # APIs Terraform itself needs before anything else exists (docs/INFRA.md §1). The main root enables
  # the runtime APIs.
  bootstrap_services = toset([
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ])

  # docs/ARCHITECTURE.md §6: containers only; values arrive by `make secrets-push`, `make dns` and
  # `make stripe-setup`, never through Terraform state.
  secret_ids = toset([
    "anthropic-api-key",
    "gemini-api-key",
    "resend-api-key",
    "stripe-secret-key",
    "stripe-webhook-secret",
  ])

  # docs/ARCHITECTURE.md §5: project roles of github-deployer@, exactly; never roles/owner or
  # roles/editor. roles/artifactregistry.writer is granted on the repository (registry.tf);
  # roles/iam.serviceAccountUser on the runtime accounts is granted where those accounts are created
  # (infra/main/iam.tf), because they do not exist when this root is applied.
  # roles/resourcemanager.projectIamAdmin is NOT in this set: it is granted only with a condition
  # (wif.tf), and an unconditional binding for the same role would override it (F410).
  deployer_project_roles = toset([
    "roles/cloudscheduler.admin",
    "roles/datastore.owner",
    "roles/iam.serviceAccountAdmin",
    "roles/logging.configWriter",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ])

  # Project roles the deployer may grant: exactly the project-level grants in infra/main/iam.tf
  # (datastore.user for reel-api and reel-editor). Never a role that carries setIamPolicy (F410).
  deployer_grantable_roles = ["roles/datastore.user"]

  # GitHub environment whose jobs Kevin approves; only its jobs may act as the deployer (F411).
  github_environment = "beta"

  # D59: a $10 a month warning budget, alerting at 50 %, 90 % and 100 %.
  budget_units      = "10"
  budget_thresholds = [0.5, 0.9, 1.0]

  # docs/INFRA.md §2 cleanup: delete any version older than 30 days, keep the 5 newest (keep wins).
  image_max_age     = "2592000s" # 30 days
  image_keep_recent = 5

  # 7 days, the Cloud Storage default (F50), written out: an extra safety net for state files.
  state_soft_delete_seconds = 604800

  # GitHub's OIDC issuer for Actions tokens.
  github_oidc_issuer = "https://token.actions.githubusercontent.com"
}
