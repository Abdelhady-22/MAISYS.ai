terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }

  # The state bucket itself is bootstrapped manually before the first
  # `terraform init` — see README.md for the gcloud commands.
  backend "gcs" {
    bucket = "maisys-tf-state-gcp"
    prefix = "gcp/dev"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

data "google_project" "current" {}

locals {
  common_labels = {
    project    = "maisys"
    env        = var.env
    managed_by = "terraform"
  }
}
