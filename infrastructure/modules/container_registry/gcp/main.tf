terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

resource "google_artifact_registry_repository" "this" {
  repository_id = var.name
  location      = var.location
  format        = var.format
  description   = var.description
  labels        = var.labels
}
