output "aks_name" {
  description = "Name of the AKS cluster."
  value       = module.aks.name
}

output "aks_endpoint" {
  description = "API server FQDN of the AKS cluster."
  value       = module.aks.endpoint
  sensitive   = true
}

output "aks_ca_cert" {
  description = "Base64-encoded AKS cluster CA certificate."
  value       = module.aks.ca_cert
  sensitive   = true
}

output "acr_login_server" {
  description = "Docker-pullable ACR URL (e.g. maisysstage.azurecr.io)."
  value       = module.acr.login_server
}

output "key_vault_uri" {
  description = "URI of the Key Vault."
  value       = module.key_vault.uri
}

output "gha_client_id" {
  description = "Client ID of the user-assigned identity GitHub Actions impersonates. Set as the AZURE_CLIENT_ID GitHub Actions secret."
  value       = azurerm_user_assigned_identity.maisys_workload.client_id
}

output "gha_federated_credential_subject" {
  description = "Federated credential subject pattern. Use it to verify the GitHub Actions workflow's expected OIDC claim."
  value       = azurerm_federated_identity_credential.gha_stage.subject
}
