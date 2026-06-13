variable "subscription_id" {
  description = "Azure subscription ID."
  type        = string
}

variable "tenant_id" {
  description = "Azure AD tenant ID."
  type        = string
}

variable "location" {
  description = "Default Azure region."
  type        = string
  default     = "eastus"
}

variable "env" {
  description = "Environment label baked into resource names and tags."
  type        = string
  default     = "stage"
}

variable "github_repo" {
  description = "GitHub repository in 'owner/repo' format. Used by the federated credential subject."
  type        = string

  validation {
    condition     = can(regex("^[^/[:space:]]+/[^/[:space:]]+$", var.github_repo))
    error_message = "github_repo must be in 'owner/repo' format (no slashes or whitespace in either segment)."
  }
}

variable "github_branch" {
  description = "Branch that triggers Azure deploys. Federated credential is scoped to this branch only."
  type        = string
  default     = "stage"
}

variable "operator_object_id" {
  description = "Azure AD object ID of the human operator (your user). Gets full Key Vault access."
  type        = string
}

variable "data_storage_account_name" {
  description = "Name of the data storage account (3-24 lowercase alphanumeric)."
  type        = string
  default     = "maisysstage"
}

variable "data_container_name" {
  description = "Name of the data blob container."
  type        = string
  default     = "maisys-data-stage"
}
