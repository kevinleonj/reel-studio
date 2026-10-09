# D60, F36: Terraform and provider versions are pinned for both roots.
# State starts as a local file (Kevin applies once from his laptop, docs/INFRA.md §1); after the first
# apply it moves into the state bucket with `terraform init -migrate-state` and a backend "gcs" block
# (prefix "bootstrap"). Until then there is deliberately no backend block.
terraform {
  required_version = "= 1.16.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.6"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = local.region
  # The Budget API rejects user credentials without a quota project; bill API calls to this project.
  billing_project       = var.project_id
  user_project_override = true
}
