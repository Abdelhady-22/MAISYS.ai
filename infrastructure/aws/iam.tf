# ──────────────────────────────────────────────────────────────────────────
# GitHub Actions OIDC provider
# ──────────────────────────────────────────────────────────────────────────
# GitHub Actions runners present an OIDC token at https://token.actions.
# githubusercontent.com. AWS validates that token against this provider;
# successful validation lets the workflow call sts:AssumeRoleWithWebIdentity
# on aws_iam_role.gha_deploy. The thumbprint is auto-trusted by AWS for
# this issuer, but the IAM API still accepts (and historically required) a
# value; we keep one valid certificate fingerprint for backwards compat.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]

  tags = local.common_labels
}

# ──────────────────────────────────────────────────────────────────────────
# IAM role assumed by GitHub Actions to push images and deploy to EKS
# ──────────────────────────────────────────────────────────────────────────
# Trust policy: only an OIDC token whose 'aud' is sts.amazonaws.com AND
# whose 'sub' is exactly the configured repo + branch combo can assume
# this role. StringEquals (not StringLike) is used so wildcards don't
# silently widen the scope.
data "aws_iam_policy_document" "gha_deploy_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "gha_deploy" {
  name               = "maisys-gha-deploy-${var.env}"
  description        = "Federated identity for GitHub Actions deploys to ${var.env}."
  assume_role_policy = data.aws_iam_policy_document.gha_deploy_trust.json
  tags               = local.common_labels
}

# Permissions granted to the GHA role:
#  - ECR push (pre-built managed policy covers GetAuthorizationToken,
#    BatchCheckLayerAvailability, PutImage, etc.).
#  - EKS DescribeCluster, so `aws eks update-kubeconfig` works from CI.
#  - Listing/getting EKS itself (read-only).
resource "aws_iam_role_policy_attachment" "gha_ecr_push" {
  role       = aws_iam_role.gha_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

data "aws_iam_policy_document" "gha_eks_describe" {
  statement {
    effect    = "Allow"
    actions   = ["eks:DescribeCluster", "eks:ListClusters"]
    resources = [module.eks.arn]
  }
}

resource "aws_iam_role_policy" "gha_eks_describe" {
  name   = "eks-describe"
  role   = aws_iam_role.gha_deploy.id
  policy = data.aws_iam_policy_document.gha_eks_describe.json
}

# ──────────────────────────────────────────────────────────────────────────
# IRSA roles — one IAM role per service, assumable only by the matching
# Kubernetes ServiceAccount in the configured namespace.
# ──────────────────────────────────────────────────────────────────────────
# The OIDC condition keys use the cluster's issuer hostname+path (without
# the https:// prefix). The sub claim format is fixed by EKS:
#   system:serviceaccount:<namespace>:<service-account-name>
# Apps annotate their k8s SA with eks.amazonaws.com/role-arn = <this ARN>;
# the pod is then issued a projected JWT and assumes this role automatically.
#
# Starts with empty permissions on purpose — each service adds the specific
# policies it needs (S3 read for data services, Secrets Manager read for
# services that fetch credentials, etc.) in follow-up PRs.

locals {
  # Strip the scheme so the resulting string can be used as the condition
  # key prefix (AWS requires the bare issuer hostname+path).
  oidc_issuer_bare = replace(module.eks.oidc_issuer_url, "https://", "")
}

data "aws_iam_policy_document" "irsa_trust" {
  for_each = toset(var.services)

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer_bare}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer_bare}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${each.key}"]
    }
  }
}

resource "aws_iam_role" "irsa" {
  for_each = toset(var.services)

  name               = "maisys-irsa-${each.key}-${var.env}"
  description        = "IRSA role for ${each.key} pods in namespace '${var.k8s_namespace}'."
  assume_role_policy = data.aws_iam_policy_document.irsa_trust[each.key].json
  tags               = local.common_labels
}
