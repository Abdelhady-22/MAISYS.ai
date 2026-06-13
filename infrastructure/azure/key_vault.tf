module "key_vault" {
  source = "../modules/secret_store/azure"

  name                = "maisys-${var.env}-kv"
  location            = azurerm_resource_group.maisys_stage_rg.location
  resource_group_name = azurerm_resource_group.maisys_stage_rg.name
  tenant_id           = var.tenant_id
  sku_name            = "standard"

  # Soft-delete is mandatory; purge protection is OFF for stage so the vault
  # can be torn down at end-of-project. Flip to true before production.
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  access_policies = [
    # 1. Human operator: full secret + key + cert management.
    {
      object_id = var.operator_object_id
      secret_permissions = [
        "Get", "List", "Set", "Delete", "Recover", "Backup", "Restore", "Purge",
      ]
      key_permissions = [
        "Get", "List", "Create", "Delete", "Recover", "Backup", "Restore", "Purge",
      ]
      certificate_permissions = [
        "Get", "List", "Create", "Delete", "Recover", "Backup", "Restore", "Purge",
      ]
    },
    # 2. AKS cluster system-assigned identity: read secrets at runtime via
    #    the Key Vault CSI driver / Azure SDK.
    {
      object_id          = module.aks.principal_id
      secret_permissions = ["Get", "List"]
    },
    # 3. GitHub Actions user-assigned identity: read secrets during deploys
    #    (database passwords, API tokens injected into workloads).
    {
      object_id          = azurerm_user_assigned_identity.maisys_workload.principal_id
      secret_permissions = ["Get", "List"]
    },
  ]

  labels = local.common_labels
}
