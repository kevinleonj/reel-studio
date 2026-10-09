# No defaults: every value is chosen per project (docs/INFRA.md §1). Pass them with -var on the
# command line `make bootstrap-plan` prints. Do not write a *.tfvars file: .gitignore does not cover
# it yet and the repository is public.

variable "project_id" {
  description = "Google Cloud project id created by `make gcp-project` (reel-studio-beta plus a suffix)."
  type        = string
}

variable "billing_account" {
  description = "Billing account id the project is linked to (GCP_BILLING_ACCOUNT in the laptop's dotenv file)."
  type        = string
}

variable "budget_currency_code" {
  description = "ISO 4217 code of the billing account's currency; the budget amount is in this currency (D59)."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric id of the GitHub repository allowed to deploy (gh api repos/OWNER/REPO --jq .id)."
  type        = string
}

variable "github_repository_owner_id" {
  description = "Numeric id of the repository owner (gh api repos/OWNER/REPO --jq .owner.id)."
  type        = string
}
