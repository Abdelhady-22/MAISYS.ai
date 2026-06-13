resource "azurerm_virtual_network" "maisys_vnet" {
  name                = "maisys-net-${var.env}"
  location            = azurerm_resource_group.maisys_stage_rg.location
  resource_group_name = azurerm_resource_group.maisys_stage_rg.name

  # /16 leaves plenty of room for future subnets (databases, dedicated GPU
  # pool, internal load balancers).
  address_space = ["10.0.0.0/16"]

  tags = local.common_labels
}

# Subnet sized for Azure CNI (classic, not overlay): each pod gets a VNet IP.
# With max 6 nodes × 30 pods + headroom, /22 (1024 IPs) is comfortable.
resource "azurerm_subnet" "aks" {
  name                 = "maisys-subnet-aks-${var.env}"
  resource_group_name  = azurerm_resource_group.maisys_stage_rg.name
  virtual_network_name = azurerm_virtual_network.maisys_vnet.name
  address_prefixes     = ["10.0.0.0/22"]
}
