variable "name" {
  description = "Secret short name (secret_id). Project is added automatically by GCP."
  type        = string
}

variable "labels" {
  description = "Labels applied to the secret."
  type        = map(string)
  default     = {}
}

variable "replication_locations" {
  description = "If non-empty, use user-managed replication to these regions. Otherwise automatic replication."
  type        = list(string)
  default     = []
}
