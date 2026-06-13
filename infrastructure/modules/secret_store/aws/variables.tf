variable "name" {
  description = "Secrets Manager secret name."
  type        = string
}

variable "labels" {
  description = "Labels applied as AWS tags."
  type        = map(string)
  default     = {}
}

variable "description" {
  description = "Human-readable description shown in the console."
  type        = string
  default     = ""
}

variable "recovery_window_days" {
  description = "Days a deleted secret stays recoverable (7-30). Set to 0 to force-delete immediately."
  type        = number
  default     = 7
}

variable "kms_key_id" {
  description = "Optional KMS key ARN for encryption. Default = AWS-managed key (aws/secretsmanager)."
  type        = string
  default     = null
}
