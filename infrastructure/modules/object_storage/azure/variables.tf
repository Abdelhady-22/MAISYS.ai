variable "name" {
  description = "Logical bucket name → maps to the Azure Storage Container name."
  type        = string
}

variable "storage_account_name" {
  description = "Azure-specific: parent storage account name (3-24 lowercase alphanumeric, globally unique)."
  type        = string
}

variable "location" {
  description = "Azure region (e.g. eastus)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group hosting the storage account."
  type        = string
}

variable "account_tier" {
  description = "Storage account tier: Standard or Premium."
  type        = string
  default     = "Standard"
}

variable "account_replication_type" {
  description = "Storage account replication: LRS, GRS, RAGRS, ZRS, GZRS, RAGZRS."
  type        = string
  default     = "LRS"
}

variable "access_tier" {
  description = "Default access tier for the account: Hot or Cool."
  type        = string
  default     = "Hot"
}

variable "labels" {
  description = "Labels (applied as Azure 'tags') propagated to the account and container."
  type        = map(string)
  default     = {}
}

variable "lifecycle_rules" {
  description = "Lifecycle rules emitted onto the storage account's management policy. Each rule is one filter+action set."
  type = list(object({
    name           = string
    matches_prefix = optional(list(string), [])
    tier_to_cool_after_days     = optional(number)
    tier_to_archive_after_days  = optional(number)
    delete_after_days           = optional(number)
  }))
  default = []
}

variable "versioning_enabled" {
  description = "Enable blob versioning on the account."
  type        = bool
  default     = false
}

variable "container_access_type" {
  description = "Container access level: private, blob, or container. Default private (best practice)."
  type        = string
  default     = "private"
}
