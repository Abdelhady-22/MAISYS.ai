terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.100, < 5.0"
    }
  }
}

resource "azurerm_storage_account" "this" {
  name                = var.storage_account_name
  location            = var.location
  resource_group_name = var.resource_group_name

  account_tier             = var.account_tier
  account_replication_type = var.account_replication_type
  access_tier              = var.access_tier
  account_kind             = "StorageV2"
  min_tls_version          = "TLS1_2"

  allow_nested_items_to_be_public = false
  https_traffic_only_enabled      = true

  blob_properties {
    versioning_enabled = var.versioning_enabled
  }

  tags = var.labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "this" {
  name                  = var.name
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = var.container_access_type

  lifecycle {
    prevent_destroy = true
  }
}

# Management policy applies lifecycle/tiering rules at the account level.
# Rules with matches_prefix are scoped to specific virtual prefixes within
# blobs — the typical pattern for "transition raw/** to cool after 30d".
resource "azurerm_storage_management_policy" "this" {
  count              = length(var.lifecycle_rules) > 0 ? 1 : 0
  storage_account_id = azurerm_storage_account.this.id

  dynamic "rule" {
    for_each = var.lifecycle_rules
    content {
      name    = rule.value.name
      enabled = true

      filters {
        prefix_match = [
          for p in rule.value.matches_prefix : "${azurerm_storage_container.this.name}/${trimprefix(p, "/")}"
        ]
        blob_types = ["blockBlob"]
      }

      actions {
        base_blob {
          tier_to_cool_after_days_since_modification_greater_than    = rule.value.tier_to_cool_after_days
          tier_to_archive_after_days_since_modification_greater_than = rule.value.tier_to_archive_after_days
          delete_after_days_since_modification_greater_than          = rule.value.delete_after_days
        }
      }
    }
  }
}
