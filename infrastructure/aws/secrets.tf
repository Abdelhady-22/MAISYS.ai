# Secrets Manager shells — one azure_secretsmanager_secret per name in
# var.secret_names. Terraform only creates the resource; secret VALUES are
# populated separately to keep secret material out of state.
#
# After `terraform apply`, populate each secret with:
#   aws secretsmanager put-secret-value \
#       --secret-id <name> \
#       --secret-string '<value>'
#
# See README.md §5 for the full sequence.
module "secrets" {
  for_each = toset(var.secret_names)
  source   = "../modules/secret_store/aws"

  name        = each.value
  description = "MAISYS ${var.env} — ${each.value}. Value managed outside terraform."
  labels      = local.common_labels

  # Allow 7-day recovery window after deletion (the AWS minimum). Increase
  # for prod-critical secrets.
  recovery_window_days = 7
}
