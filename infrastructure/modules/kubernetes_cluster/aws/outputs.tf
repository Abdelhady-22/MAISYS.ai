output "name" {
  description = "Cluster name."
  value       = aws_eks_cluster.this.name
}

output "endpoint" {
  description = "Kubernetes API server endpoint URL."
  value       = aws_eks_cluster.this.endpoint
  sensitive   = true
}

output "ca_cert" {
  description = "Base64-encoded cluster CA certificate."
  value       = aws_eks_cluster.this.certificate_authority[0].data
  sensitive   = true
}

output "arn" {
  description = "Cluster ARN."
  value       = aws_eks_cluster.this.arn
}

output "oidc_issuer_url" {
  description = "OIDC issuer URL of the cluster (used to construct IRSA condition keys)."
  value       = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

output "oidc_provider_arn" {
  description = "ARN of the IAM OIDC provider for the cluster. Null if enable_irsa = false."
  value       = var.enable_irsa ? aws_iam_openid_connect_provider.eks[0].arn : null
}

output "cluster_security_group_id" {
  description = "Security group AWS auto-created for the cluster."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "node_role_arn" {
  description = "IAM role ARN used by worker nodes."
  value       = aws_iam_role.node.arn
}
