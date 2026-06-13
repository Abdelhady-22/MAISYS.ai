# ACR name MUST be globally unique alphanumeric (no hyphens), so it can't
# follow the maisys-<env> pattern literally — using maisysstage instead.
module "acr" {
  source = "../modules/container_registry/azure"

  name                = "maisys${var.env}"
  location            = azurerm_resource_group.maisys_stage_rg.location
  resource_group_name = azurerm_resource_group.maisys_stage_rg.name
  sku                 = "Standard"
  admin_enabled       = false

  labels = local.common_labels
}

# Allow the AKS kubelet identity to pull from this ACR. Without this the
# cluster cannot start workloads that reference images here.
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = module.acr.id
  role_definition_name = "AcrPull"
  principal_id         = module.aks.kubelet_identity_object_id
}
