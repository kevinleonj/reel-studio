# D60, F36: Terraform and provider versions are pinned for both roots.
# State started as a local file (Kevin's first apply, 16 Oct 2026, docs/INFRA.md §1) and moved into
# the state bucket that apply created, with `terraform init -migrate-state`.
terraform {
  required_version = "= 1.16.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.6"
    }
  }

  # Partial configuration, as in infra/main: the bucket is named after the project, so init passes
  # -backend-config=bucket=<state bucket> (the state_bucket output). Validation runs with
  # -backend=false.
  backend "gcs" {
    prefix = "bootstrap"
  }
}

provider "google" {
  project = var.project_id
  region  = local.region
  # The Budget API rejects user credentials without a quota project; bill API calls to this project.
  billing_project       = var.project_id
  user_project_override = true
}
