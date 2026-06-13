variable "name" {
  description = "Repository ID (Artifact Registry repository_id)."
  type        = string
}

variable "location" {
  description = "GCP region for the repository (e.g. us-central1)."
  type        = string
}

variable "format" {
  description = "Repository format. DOCKER is the default for container images."
  type        = string
  default     = "DOCKER"
}

variable "description" {
  description = "Human-readable description shown in the GCP console."
  type        = string
  default     = ""
}

variable "labels" {
  description = "Labels applied to the repository."
  type        = map(string)
  default     = {}
}
