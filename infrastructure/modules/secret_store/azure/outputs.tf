output "id" {
  description = "Vault resource ID."
  value       = azurerm_key_vault.this.id
}

output "name" {
  description = "Vault name."
  value       = azurerm_key_vault.this.name
}

output "uri" {
  description = "Vault URI (https://<name>.vault.azure.net/)."
  value       = azurerm_key_vault.this.vault_uri
}
