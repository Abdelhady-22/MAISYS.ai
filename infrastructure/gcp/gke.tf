module "gke" {
  source = "../modules/kubernetes_cluster/gcp"

  name     = "maisys-${var.env}"
  location = var.region # regional cluster for HA across us-central1 zones

  network                       = google_compute_network.maisys_vpc.id
  subnetwork                    = google_compute_subnetwork.maisys_subnet.id
  pods_secondary_range_name     = "pods"
  services_secondary_range_name = "services"

  node_machine_type = "e2-standard-4"
  node_count        = 3
  min_node_count    = 1
  max_node_count    = 5

  release_channel = "REGULAR"

  workload_pool = "${var.project_id}.svc.id.goog"

  labels = local.common_labels
}
