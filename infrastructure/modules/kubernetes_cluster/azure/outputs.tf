output "name" {
  description = "Cluster name."
  value       = azurerm_kubernetes_cluster.this.name
}

output "location" {
  description = "Cluster region."
  value       = azurerm_kubernetes_cluster.this.location
}

output "endpoint" {
  description = "AKS API server FQDN."
  value       = azurerm_kubernetes_cluster.this.fqdn
  sensitive   = true
}

output "ca_cert" {
  description = "Base64-encoded cluster CA certificate."
  value       = azurerm_kubernetes_cluster.this.kube_config[0].cluster_ca_certificate
  sensitive   = true
}

output "kubelet_identity_object_id" {
  description = "Object ID of the AKS kubelet identity (used to grant ACR pull, etc.)."
  value       = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}

output "principal_id" {
  description = "Object ID of the cluster's system-assigned managed identity."
  value       = azurerm_kubernetes_cluster.this.identity[0].principal_id
}

output "oidc_issuer_url" {
  description = "OIDC issuer URL for Workload Identity Federation with k8s service accounts."
  value       = azurerm_kubernetes_cluster.this.oidc_issuer_url
}
