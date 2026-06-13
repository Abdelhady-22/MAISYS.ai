module "artifact_registry" {
  source = "../modules/container_registry/gcp"

  name        = "maisys-${var.env}"
  location    = var.region
  format      = "DOCKER"
  description = "Docker images for MAISYS ${var.env} environment."
  labels      = local.common_labels
}
