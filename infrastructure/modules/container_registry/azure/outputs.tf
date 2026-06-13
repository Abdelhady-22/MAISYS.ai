output "id" {
  description = "Registry resource ID."
  value       = azurerm_container_registry.this.id
}

output "name" {
  description = "Registry name."
  value       = azurerm_container_registry.this.name
}

output "url" {
  description = "Docker-pullable registry URL (azurerm calls this 'login_server')."
  value       = azurerm_container_registry.this.login_server
}

output "login_server" {
  description = "Azure-specific alias of url (matches the azurerm_container_registry attribute name)."
  value       = azurerm_container_registry.this.login_server
}
