module "aks" {
  source = "../modules/kubernetes_cluster/azure"

  name                = "maisys-${var.env}"
  location            = azurerm_resource_group.maisys_stage_rg.location
  resource_group_name = azurerm_resource_group.maisys_stage_rg.name

  subnet_id = azurerm_subnet.aks.id

  node_machine_type = "Standard_D4s_v3"
  node_count        = 3
  min_node_count    = 2
  max_node_count    = 6

  network_plugin = "azure" # Azure CNI (classic, not overlay)

  workload_identity_enabled = true
  oidc_issuer_enabled       = true

  labels = local.common_labels
}
