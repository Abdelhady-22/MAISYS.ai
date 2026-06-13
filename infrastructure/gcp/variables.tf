variable "project_id" {
  description = "GCP project ID (e.g. 'maisys-dev')."
  type        = string
}

variable "region" {
  description = "Default GCP region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Default GCP zone for zonal resources."
  type        = string
  default     = "us-central1-a"
}

variable "env" {
  description = "Environment label baked into resource names and labels."
  type        = string
  default     = "dev"
}

variable "github_repo" {
  description = "GitHub repository in 'owner/repo' format. Used to scope Workload Identity Federation."
  type        = string

  validation {
    condition     = can(regex("^[^/[:space:]]+/[^/[:space:]]+$", var.github_repo))
    error_message = "github_repo must be in 'owner/repo' format (no slashes or whitespace in either segment)."
  }
}
