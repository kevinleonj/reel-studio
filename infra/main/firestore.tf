# Firestore takes no labels; `tags` are resource-manager tags, a different mechanism, left unset.
resource "google_firestore_database" "default" {
  name             = "(default)" # the free quota applies only to (default) (F35, D53)
  location_id      = local.region
  type             = "FIRESTORE_NATIVE"
  database_edition = "STANDARD"
  # Orders live 30 days at most; recovery would be paid storage for nothing.
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_DISABLED"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  # A destroy forgets the database instead of deleting it, so orders survive a bad plan.
  deletion_policy = "ABANDON"

  depends_on = [google_project_service.runtime]
}

# Queue (status, queue.queued_at), sweep of dead leases (status, queue.lease_until) and missed
# expiries (status, created_at) on orders (D55).
resource "google_firestore_index" "orders" {
  for_each = local.orders_indexes

  database    = google_firestore_database.default.name
  collection  = local.orders_collection
  query_scope = "COLLECTION"
  api_scope   = "ANY_API"

  dynamic "fields" {
    for_each = each.value
    content {
      field_path = fields.value
      order      = "ASCENDING"
    }
  }
}

# Orders disappear once expires_at (written by the app, 30 days after creation) has passed.
# No index_config block: an empty one would switch off the inherited single-field indexes here.
resource "google_firestore_field" "orders_ttl" {
  database   = google_firestore_database.default.name
  collection = local.orders_collection
  field      = local.orders_ttl_field

  ttl_config {}

  # Enabling TTL takes ten minutes or more; waiting would outlive the 15-minute apply job
  # (docs/INFRA.md §4). Terraform then cannot see the TTL state, so `make smoke` checks it with
  # `gcloud firestore fields ttls list --collection-group=orders` (expects ACTIVE).
  skip_wait = true
}
