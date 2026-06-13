terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

# The secret itself is managed here. Secret VERSIONS (the actual values) are
# never managed by terraform — they are written manually or by application
# code via the gcloud / Secret Manager API. Keeping versions out of terraform
# avoids accidentally exposing secret material in state files.

resource "google_secret_manager_secret" "this" {
  secret_id = var.name
  labels    = var.labels

  dynamic "replication" {
    for_each = length(var.replication_locations) == 0 ? [1] : []
    content {
      auto {}
    }
  }

  dynamic "replication" {
    for_each = length(var.replication_locations) > 0 ? [1] : []
    content {
      user_managed {
        dynamic "replicas" {
          for_each = var.replication_locations
          content {
            location = replicas.value
          }
        }
      }
    }
  }
}
