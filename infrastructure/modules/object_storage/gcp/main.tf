terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

resource "google_storage_bucket" "this" {
  name                        = var.name
  location                    = var.location
  storage_class               = var.storage_class
  labels                      = var.labels
  uniform_bucket_level_access = var.uniform_bucket_level_access
  force_destroy               = var.force_destroy

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "lifecycle_rule" {
    for_each = var.lifecycle_rules
    content {
      action {
        type          = lifecycle_rule.value.action_type
        storage_class = lifecycle_rule.value.storage_class
      }
      condition {
        age            = lifecycle_rule.value.age_days
        matches_prefix = lifecycle_rule.value.matches_prefix
      }
    }
  }

  # Data buckets must not be destroyed by terraform. To intentionally
  # delete one, remove this block in a focused PR.
  lifecycle {
    prevent_destroy = true
  }
}
