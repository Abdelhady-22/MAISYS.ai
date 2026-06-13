terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.100, < 5.0"
    }
  }
}

resource "azurerm_key_vault" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  sku_name            = var.sku_name

  soft_delete_retention_days = var.soft_delete_retention_days
  purge_protection_enabled   = var.purge_protection_enabled
  enable_rbac_authorization  = false

  tags = var.labels
}

# Per-principal access policies. One azurerm_key_vault_access_policy per
# entry in var.access_policies. Each principal gets only the permissions
# explicitly listed — no role inheritance.
resource "azurerm_key_vault_access_policy" "this" {
  for_each = {
    for idx, ap in var.access_policies : ap.object_id => ap
  }

  key_vault_id = azurerm_key_vault.this.id
  tenant_id    = var.tenant_id
  object_id    = each.value.object_id

  secret_permissions      = each.value.secret_permissions
  key_permissions         = each.value.key_permissions
  certificate_permissions = each.value.certificate_permissions
}
