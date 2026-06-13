# One ECR repository per service. The for_each iteration creates 14 module
# instances; each one declares a single aws_ecr_repository at path
# "maisys/<service>". The repository_url is exposed back through
# module.ecr["<service>"].url.
module "ecr" {
  for_each = toset(var.services)
  source   = "../modules/container_registry/aws"

  name                   = "maisys/${each.value}"
  labels                 = local.common_labels
  image_tag_mutability   = "MUTABLE"
  image_scanning_enabled = true
}
