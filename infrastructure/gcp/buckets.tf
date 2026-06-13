# Existing bucket — reconcile with reality via `terraform import`. See README.md.
module "data_bucket" {
  source = "../modules/object_storage/gcp"

  name          = "maisys-data-${var.env}"
  location      = upper(var.region)
  storage_class = "STANDARD"
  labels        = local.common_labels

  # Lifecycle: transition raw/** to Coldline after 30 days, Archive after 180.
  # The default storage class is STANDARD so that ingestion writes are cheap;
  # cold transitions kick in once the data is no longer hot.
  lifecycle_rules = [
    {
      action_type    = "SetStorageClass"
      storage_class  = "COLDLINE"
      age_days       = 30
      matches_prefix = ["raw/"]
    },
    {
      action_type    = "SetStorageClass"
      storage_class  = "ARCHIVE"
      age_days       = 180
      matches_prefix = ["raw/"]
    },
  ]
}
