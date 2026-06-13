variable "name" {
  description = "Key Vault name (3-24 chars, alphanumeric + hyphens, must start with letter, globally unique)."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group hosting the vault."
  type        = string
}

variable "tenant_id" {
  description = "Azure AD tenant ID for the vault."
  type        = string
}

variable "sku_name" {
  description = "Vault SKU: standard or premium."
  type        = string
  default     = "standard"
}

variable "soft_delete_retention_days" {
  description = "Days that deleted secrets remain recoverable (7-90). Cannot be disabled."
  type        = number
  default     = 7
}

variable "purge_protection_enabled" {
  description = "Block hard-delete of the vault. Once enabled cannot be turned off."
  type        = bool
  default     = false
}

variable "access_policies" {
  description = "Per-principal access policy entries. Each grants the listed permissions to one object_id."
  type = list(object({
    object_id               = string
    secret_permissions      = optional(list(string), [])
    key_permissions         = optional(list(string), [])
    certificate_permissions = optional(list(string), [])
  }))
  default = []
}

variable "labels" {
  description = "Labels applied as Azure tags."
  type        = map(string)
  default     = {}
}
