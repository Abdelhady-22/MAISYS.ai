terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.50"
    }
  }

  # State bucket is bootstrapped manually — see README.md.
  backend "azurerm" {
    resource_group_name  = "maisys-stage-rg"
    storage_account_name = "maisystfstate"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  features {}
}

provider "azuread" {
  tenant_id = var.tenant_id
}

data "azurerm_client_config" "current" {}

locals {
  common_labels = {
    project    = "maisys"
    env        = var.env
    managed_by = "terraform"
  }
}

# Resource group is imported — see README.md §3. Created by hand during
# Phase 1 ramp-up; terraform takes over its lifecycle going forward.
resource "azurerm_resource_group" "maisys_stage_rg" {
  name     = "maisys-${var.env}-rg"
  location = var.location
  tags     = local.common_labels

  lifecycle {
    prevent_destroy = true
  }
}
