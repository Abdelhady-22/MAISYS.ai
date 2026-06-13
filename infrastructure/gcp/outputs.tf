output "gke_cluster_name" {
  description = "Name of the GKE cluster."
  value       = module.gke.name
}

output "gke_endpoint" {
  description = "API server endpoint for the GKE cluster."
  value       = module.gke.endpoint
  sensitive   = true
}

output "gke_ca_cert" {
  description = "Base64-encoded cluster CA certificate."
  value       = module.gke.ca_cert
  sensitive   = true
}

output "artifact_registry_url" {
  description = "Docker-pullable Artifact Registry URL (without trailing image name)."
  value       = module.artifact_registry.url
}

output "gha_workload_identity_provider" {
  description = "Full resource name of the GitHub Actions Workload Identity provider. Set this as the GCP_WIF_PROVIDER GitHub Actions secret."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "gha_service_account_email" {
  description = "Email of the deploy service account GitHub Actions impersonates. Set this as the GCP_DEPLOY_SA GitHub Actions secret."
  value       = google_service_account.gha_deploy.email
}
