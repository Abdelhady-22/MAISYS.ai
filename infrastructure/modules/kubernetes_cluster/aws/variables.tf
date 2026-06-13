variable "name" {
  description = "EKS cluster name."
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Null = use the latest supported."
  type        = string
  default     = null
}

variable "subnet_ids" {
  description = "Subnets where EKS-managed control-plane ENIs and worker nodes live. Use the private subnets."
  type        = list(string)
}

variable "node_machine_type" {
  description = "EC2 instance type for the default node group."
  type        = string
  default     = "m5.large"
}

variable "node_count" {
  description = "Initial node count for the default node group."
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

variable "node_disk_size_gb" {
  description = "Root EBS volume size per node."
  type        = number
  default     = 50
}

variable "node_capacity_type" {
  description = "ON_DEMAND or SPOT for the default node group."
  type        = string
  default     = "ON_DEMAND"
}

variable "endpoint_public_access" {
  description = "Allow kubectl from the public internet (still IAM-gated). False = bastion / VPN only."
  type        = bool
  default     = true
}

variable "endpoint_private_access" {
  description = "Allow control-plane access from within the VPC."
  type        = bool
  default     = true
}

variable "enable_irsa" {
  description = "Create an aws_iam_openid_connect_provider for the cluster's OIDC issuer, enabling IRSA."
  type        = bool
  default     = true
}

variable "labels" {
  description = "Labels applied as AWS tags to the cluster and node group."
  type        = map(string)
  default     = {}
}
