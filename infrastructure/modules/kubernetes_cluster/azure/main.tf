terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.100, < 5.0"
    }
  }
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.dns_prefix != "" ? var.dns_prefix : var.name

  kubernetes_version = var.kubernetes_version

  oidc_issuer_enabled       = var.oidc_issuer_enabled
  workload_identity_enabled = var.workload_identity_enabled

  default_node_pool {
    name                 = "default"
    vm_size              = var.node_machine_type
    node_count           = var.node_count
    auto_scaling_enabled = true
    min_count            = var.min_node_count
    max_count            = var.max_node_count
    vnet_subnet_id       = var.subnet_id

    upgrade_settings {
      max_surge = "33%"
    }
  }

  network_profile {
    network_plugin    = var.network_plugin
    service_cidr      = var.service_cidr
    dns_service_ip    = var.dns_service_ip
    load_balancer_sku = "standard"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.labels
}
