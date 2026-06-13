# S3 bucket already exists — brought under terraform via `terraform import`.
# See README.md §3 for the exact import commands.
#
# Lifecycle policy mirrors the GCP/Azure side: transition raw/** to
# STANDARD_IA after 30 days, then GLACIER after 180. Matches DATA_PLAN.md
# §4.3 (raw/** → S3 IA per the cross-cloud parity table).
module "data_bucket" {
  source = "../modules/object_storage/aws"

  name               = "maisys-data-${var.env}"
  labels             = local.common_labels
  versioning_enabled = true
  force_destroy      = false

  lifecycle_rules = [
    {
      name                           = "raw-tiering"
      matches_prefix                 = "raw/"
      tier_to_standard_ia_after_days = 30
      tier_to_glacier_after_days     = 180
    },
  ]
}
