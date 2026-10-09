data "google_project" "this" {
  project_id = var.project_id
}

# D59: a warning, not a stop. Default recipients are the billing account's administrators and users.
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name    = "reel-studio-beta monthly"

  budget_filter {
    projects        = ["projects/${data.google_project.this.number}"]
    calendar_period = "MONTH"
    # Net of credits: the warning is about money that reaches the card. The default, written out
    # because it decides what the budget measures.
    credit_types_treatment = "INCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = local.budget_units
    }
  }

  dynamic "threshold_rules" {
    for_each = local.budget_thresholds
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  # No all_updates_rule block: provider 8.6.0 requires a Pub/Sub topic or a monitoring channel inside
  # it (terraform validate), and without it the budget emails the billing account's administrators
  # and users, which is what docs/INFRA.md §2 asks for (FACTS F77).

  depends_on = [google_project_service.bootstrap]
}
