variable "name" {
  description = "Globally unique bucket name."
  type        = string
}

variable "location" {
  description = "GCS location (e.g. US-CENTRAL1 for a regional bucket, US for multi-region)."
  type        = string
}

variable "storage_class" {
  description = "Default storage class: STANDARD, NEARLINE, COLDLINE, or ARCHIVE."
  type        = string
  default     = "STANDARD"
}

variable "labels" {
  description = "Labels applied to the bucket."
  type        = map(string)
  default     = {}
}

variable "lifecycle_rules" {
  description = "Lifecycle rules. Each rule emits one google_storage_bucket.lifecycle_rule block."
  type = list(object({
    action_type    = string
    storage_class  = optional(string)
    age_days       = optional(number)
    matches_prefix = optional(list(string))
  }))
  default = []
}

variable "versioning_enabled" {
  description = "Enable object versioning."
  type        = bool
  default     = false
}

variable "uniform_bucket_level_access" {
  description = "Disable ACLs in favour of IAM. Best practice; required for many integrations."
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete a non-empty bucket. Only true in throwaway envs."
  type        = bool
  default     = false
}
