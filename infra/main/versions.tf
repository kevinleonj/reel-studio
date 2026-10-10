# D60, F36. Applied only by .github/workflows/deploy.yml after a manual approval (docs/INFRA.md §1).
terraform {
  required_version = "= 1.16.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.6"
    }
  }

  # Partial configuration: the bucket is named after the project, so deploy.yml passes
  # -backend-config=bucket=<state bucket> (a bootstrap output). Validation runs with -backend=false.
  backend "gcs" {
    prefix = "main"
  }
}

provider "google" {
  project = var.project_id
  region  = local.region
}
