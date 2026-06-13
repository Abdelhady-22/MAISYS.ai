variable "name" {
  description = "Cluster name."
  type        = string
}

variable "location" {
  description = "GCP region (regional cluster) or zone (zonal cluster). Pass a region for regional."
  type        = string
}

variable "network" {
  description = "VPC network self_link or ID to attach the cluster to."
  type        = string
}

variable "subnetwork" {
  description = "Subnetwork self_link or ID to host nodes."
  type        = string
}

variable "pods_secondary_range_name" {
  description = "Name of the secondary range on the subnetwork used for pod IPs."
  type        = string
}

variable "services_secondary_range_name" {
  description = "Name of the secondary range on the subnetwork used for service ClusterIPs."
  type        = string
}

variable "node_machine_type" {
  description = "GCE machine type for the default node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "node_count" {
  description = "Initial node count for the default node pool."
  type        = number
  default     = 3
}

variable "min_node_count" {
  description = "Autoscaling minimum for the default node pool."
  type        = number
  default     = 1
}

variable "max_node_count" {
  description = "Autoscaling maximum for the default node pool."
  type        = number
  default     = 5
}

variable "release_channel" {
  description = "GKE release channel: RAPID, REGULAR, or STABLE."
  type        = string
  default     = "REGULAR"
}

variable "workload_pool" {
  description = "Workload Identity pool, conventionally '<project>.svc.id.goog'."
  type        = string
}

variable "labels" {
  description = "Labels applied to the cluster and to the default node pool's nodes."
  type        = map(string)
  default     = {}
}

variable "deletion_protection" {
  description = "Block terraform-driven deletion of the cluster. Always true in dev+."
  type        = bool
  default     = true
}
