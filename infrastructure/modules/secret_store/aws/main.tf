terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.30, < 6.0"
    }
  }
}

# Only the secret CONTAINER is managed by terraform — never the value.
# Operators populate values via:
#   aws secretsmanager put-secret-value --secret-id <name> --secret-string '<value>'
# This keeps secret material out of terraform state.

resource "aws_secretsmanager_secret" "this" {
  name                    = var.name
  description             = var.description
  kms_key_id              = var.kms_key_id
  recovery_window_in_days = var.recovery_window_days
  tags                    = var.labels
}
