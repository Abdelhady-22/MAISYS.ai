variable "name" {
  description = "Cluster name."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group hosting the cluster."
  type        = string
}

variable "dns_prefix" {
  description = "DNS prefix for the AKS API server FQDN. Defaults to the cluster name."
  type        = string
  default     = ""
}

variable "kubernetes_version" {
  description = "AKS Kubernetes version. Leave null to use AKS default for the region."
  type        = string
  default     = null
}

variable "subnet_id" {
  description = "Subnet ID for the default node pool."
  type        = string
}

variable "node_machine_type" {
  description = "VM size for the default node pool."
  type        = string
  default     = "Standard_D4s_v3"
}

variable "node_count" {
  description = "Initial node count for the default pool."
  type        = number
  default     = 3
}

variable "min_node_count" {
  description = "Autoscaling minimum."
  type        = number
  default     = 2
}

variable "max_node_count" {
  description = "Autoscaling maximum."
  type        = number
  default     = 6
}

variable "network_plugin" {
  description = "AKS network plugin: 'azure' (Azure CNI) or 'kubenet'."
  type        = string
  default     = "azure"
}

variable "service_cidr" {
  description = "CIDR for Kubernetes ClusterIP services. Must not overlap with the VNet."
  type        = string
  default     = "172.16.0.0/16"
}

variable "dns_service_ip" {
  description = "Cluster DNS service IP. Must sit inside service_cidr."
  type        = string
  default     = "172.16.0.10"
}

variable "workload_identity_enabled" {
  description = "Enable AKS Workload Identity (replaces pod-identity)."
  type        = bool
  default     = true
}

variable "oidc_issuer_enabled" {
  description = "Enable the AKS OIDC issuer (required for Workload Identity)."
  type        = bool
  default     = true
}

variable "labels" {
  description = "Labels applied as Azure tags."
  type        = map(string)
  default     = {}
}
