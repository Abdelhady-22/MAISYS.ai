output "name" {
  description = "Cluster name."
  value       = google_container_cluster.this.name
}

output "location" {
  description = "Cluster location (region for regional clusters)."
  value       = google_container_cluster.this.location
}

output "endpoint" {
  description = "Public API server endpoint."
  value       = google_container_cluster.this.endpoint
  sensitive   = true
}

output "ca_cert" {
  description = "Base64-encoded cluster CA certificate."
  value       = google_container_cluster.this.master_auth[0].cluster_ca_certificate
  sensitive   = true
}
