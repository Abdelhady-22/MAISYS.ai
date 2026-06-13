resource "google_compute_network" "maisys_vpc" {
  name                    = "maisys-net-${var.env}"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "MAISYS VPC for ${var.env} environment."
}

resource "google_compute_subnetwork" "maisys_subnet" {
  name        = "maisys-subnet-${var.env}"
  network     = google_compute_network.maisys_vpc.id
  region      = var.region
  description = "Primary subnet hosting GKE nodes for ${var.env}."

  ip_cidr_range = "10.10.0.0/20"

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/14"
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }

  private_ip_google_access = true
}
