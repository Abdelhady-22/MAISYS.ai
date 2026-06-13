module "eks" {
  source = "../modules/kubernetes_cluster/aws"

  name = local.cluster_name

  # Both control plane ENIs and worker nodes live in the private subnets.
  # The public subnets carry only the NAT GW and (eventually) internet-
  # facing load balancers auto-created by the AWS Load Balancer Controller.
  subnet_ids = [for s in aws_subnet.private : s.id]

  node_machine_type = "m5.large"
  node_count        = 3
  min_node_count    = 2
  max_node_count    = 6
  node_disk_size_gb = 50

  endpoint_public_access  = true
  endpoint_private_access = true

  enable_irsa = true

  labels = local.common_labels
}
