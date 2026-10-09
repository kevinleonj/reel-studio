# Five containers and no versions: values never enter Terraform state (docs/INFRA.md §2, D62).
resource "google_secret_manager_secret" "this" {
  for_each = local.secret_ids

  secret_id = each.value

  replication {
    user_managed {
      replicas {
        location = local.region
      }
    }
  }

  # Destroying a container also destroys the values written by `make secrets-push`, `make dns` and
  # `make stripe-setup`; that must be a deliberate edit.
  deletion_protection = true

  labels = merge(local.labels, { component = "secrets" })

  depends_on = [google_project_service.bootstrap]
}
