# Storage account + container both exist already; brought into terraform
# via `terraform import`. See README.md §3 for the exact import commands.
#
# Storage account name MUST be globally unique and is constrained to 3-24
# lowercase alphanumeric chars — that's why it's "maisysstage" rather than
# "maisys-data-stage". The container name carries the logical identity.
module "data_bucket" {
  source = "../modules/object_storage/azure"

  name                 = var.data_container_name
  storage_account_name = var.data_storage_account_name
  resource_group_name  = azurerm_resource_group.maisys_stage_rg.name
  location             = azurerm_resource_group.maisys_stage_rg.location

  account_tier             = "Standard"
  account_replication_type = "LRS"
  access_tier              = "Hot"

  labels = local.common_labels

  # Lifecycle: transition raw/** to Cool after 30 days, Archive after 180.
  # Mirrors the GCP-side policy exactly. Tier moves only — never delete.
  lifecycle_rules = [
    {
      name                       = "raw-tiering"
      matches_prefix             = ["raw/"]
      tier_to_cool_after_days    = 30
      tier_to_archive_after_days = 180
    },
  ]
}
