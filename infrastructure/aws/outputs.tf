output "eks_cluster_name" {
  description = "Name of the EKS cluster."
  value       = module.eks.name
}

output "eks_endpoint" {
  description = "Kubernetes API server endpoint URL."
  value       = module.eks.endpoint
  sensitive   = true
}

output "eks_ca_cert" {
  description = "Base64-encoded cluster CA certificate."
  value       = module.eks.ca_cert
  sensitive   = true
}

output "eks_oidc_provider_arn" {
  description = "ARN of the IAM OIDC provider for the EKS cluster (used in IRSA trust policies)."
  value       = module.eks.oidc_provider_arn
}

output "ecr_registry_url" {
  description = "Account+region ECR registry URL (without repo path). All repos in this account/region share this prefix."
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
}

output "ecr_repository_urls" {
  description = "Map of service-name → full ECR pull URL."
  value       = { for k, m in module.ecr : k => m.url }
}

output "gha_role_arn" {
  description = "ARN of the IAM role GitHub Actions assumes via OIDC. Set as the AWS_DEPLOY_ROLE_ARN GitHub Actions secret."
  value       = aws_iam_role.gha_deploy.arn
}

output "aws_account_id" {
  description = "AWS account ID. Set as the AWS_ACCOUNT_ID GitHub Actions secret."
  value       = data.aws_caller_identity.current.account_id
}

output "irsa_role_arns" {
  description = "Map of service-name → IRSA IAM role ARN. Annotate matching k8s ServiceAccounts with these."
  value       = { for k, r in aws_iam_role.irsa : k => r.arn }
}
