output "id" {
  description = "Storage container resource ID."
  value       = azurerm_storage_container.this.id
}

output "name" {
  description = "Container name (the logical bucket name)."
  value       = azurerm_storage_container.this.name
}

output "url" {
  description = "Cloud-agnostic bucket URL (https:// for Azure Blob)."
  value       = "https://${azurerm_storage_account.this.name}.blob.core.windows.net/${azurerm_storage_container.this.name}"
}

output "storage_account_id" {
  description = "Azure-specific: parent storage account resource ID."
  value       = azurerm_storage_account.this.id
}

output "storage_account_name" {
  description = "Azure-specific: parent storage account name."
  value       = azurerm_storage_account.this.name
}
