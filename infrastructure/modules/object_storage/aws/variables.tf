variable "name" {
  description = "Globally unique S3 bucket name."
  type        = string
}

variable "labels" {
  description = "Labels (applied as AWS 'tags') propagated to the bucket and its sub-resources."
  type        = map(string)
  default     = {}
}

variable "versioning_enabled" {
  description = "Enable object versioning on the bucket."
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Allow 'terraform destroy' to empty the bucket and delete it. Only true in throwaway envs."
  type        = bool
  default     = false
}

variable "lifecycle_rules" {
  description = "Lifecycle rules. Each rule emits one aws_s3_bucket_lifecycle_configuration.rule block."
  type = list(object({
    name                              = string
    matches_prefix                    = optional(string)
    tier_to_standard_ia_after_days    = optional(number)
    tier_to_intelligent_after_days    = optional(number)
    tier_to_glacier_ir_after_days     = optional(number)
    tier_to_glacier_after_days        = optional(number)
    tier_to_deep_archive_after_days   = optional(number)
    delete_after_days                 = optional(number)
  }))
  default = []
}

variable "sse_algorithm" {
  description = "Server-side encryption algorithm: AES256 (S3-managed) or aws:kms."
  type        = string
  default     = "AES256"
}

variable "kms_master_key_id" {
  description = "KMS key ARN, required if sse_algorithm is aws:kms. Ignored for AES256."
  type        = string
  default     = null
}
