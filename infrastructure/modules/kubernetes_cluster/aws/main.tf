terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.30, < 6.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0"
    }
  }
}

# ──────────────────────────────────────────────────────────────────────────
# IAM role assumed by the EKS control plane itself
# ──────────────────────────────────────────────────────────────────────────
data "aws_iam_policy_document" "cluster_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${var.name}-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.cluster_assume_role.json
  tags               = var.labels
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# ──────────────────────────────────────────────────────────────────────────
# EKS cluster
# ──────────────────────────────────────────────────────────────────────────
resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = var.endpoint_private_access
    endpoint_public_access  = var.endpoint_public_access
  }

  # Modern EKS access mode. API_AND_CONFIG_MAP keeps the legacy aws-auth
  # ConfigMap working alongside the new access entries API.
  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true
  }

  tags = var.labels

  depends_on = [aws_iam_role_policy_attachment.cluster_policy]
}

# ──────────────────────────────────────────────────────────────────────────
# IAM role assumed by worker nodes (kubelet, kube-proxy, CNI, ECR pull)
# ──────────────────────────────────────────────────────────────────────────
data "aws_iam_policy_document" "node_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${var.name}-node-role"
  assume_role_policy = data.aws_iam_policy_document.node_assume_role.json
  tags               = var.labels
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# ──────────────────────────────────────────────────────────────────────────
# Default managed node group
# ──────────────────────────────────────────────────────────────────────────
resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "default"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.subnet_ids

  capacity_type  = var.node_capacity_type
  instance_types = [var.node_machine_type]
  disk_size      = var.node_disk_size_gb

  scaling_config {
    desired_size = var.node_count
    min_size     = var.min_node_count
    max_size     = var.max_node_count
  }

  update_config {
    max_unavailable = 1
  }

  tags = var.labels

  # Ensure the worker role has its policies BEFORE nodes try to join,
  # otherwise kubelet auth fails and the node group goes UNHEALTHY.
  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_cni,
    aws_iam_role_policy_attachment.node_ecr,
  ]
}

# ──────────────────────────────────────────────────────────────────────────
# IAM OIDC provider — required for IRSA (IAM Roles for Service Accounts)
# ──────────────────────────────────────────────────────────────────────────
# Fetch the SHA-1 thumbprint of the EKS OIDC issuer's TLS cert. AWS no
# longer strictly requires the thumbprint for EKS issuers (auto-trusted
# since 2023) but the IAM API still accepts it for backwards compat.
data "tls_certificate" "eks" {
  count = var.enable_irsa ? 1 : 0
  url   = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  count = var.enable_irsa ? 1 : 0

  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks[0].certificates[0].sha1_fingerprint]

  tags = var.labels
}
