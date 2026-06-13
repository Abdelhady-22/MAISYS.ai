variable "name" {
  description = "ACR name (5-50 chars, alphanumeric only, globally unique)."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group hosting the registry."
  type        = string
}

variable "sku" {
  description = "ACR SKU: Basic, Standard, or Premium."
  type        = string
  default     = "Standard"
}

variable "labels" {
  description = "Labels applied as Azure tags."
  type        = map(string)
  default     = {}
}

variable "admin_enabled" {
  description = "Enable the admin user (username/password auth). Keep false; use AAD/managed identities instead."
  type        = bool
  default     = false
}
