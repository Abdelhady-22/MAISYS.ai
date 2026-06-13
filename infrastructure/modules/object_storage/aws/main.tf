terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.30, < 6.0"
    }
  }
}

resource "aws_s3_bucket" "this" {
  bucket        = var.name
  force_destroy = var.force_destroy
  tags          = var.labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = var.versioning_enabled ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.sse_algorithm
      kms_master_key_id = var.sse_algorithm == "aws:kms" ? var.kms_master_key_id : null
    }
  }
}

# All four flags ON — best practice for non-public buckets. Without this,
# bucket ACLs or a future bucket policy could expose data publicly.
resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  count  = length(var.lifecycle_rules) > 0 ? 1 : 0
  bucket = aws_s3_bucket.this.id

  dynamic "rule" {
    for_each = var.lifecycle_rules
    content {
      id     = rule.value.name
      status = "Enabled"

      filter {
        prefix = rule.value.matches_prefix != null ? rule.value.matches_prefix : ""
      }

      dynamic "transition" {
        for_each = rule.value.tier_to_standard_ia_after_days != null ? [1] : []
        content {
          days          = rule.value.tier_to_standard_ia_after_days
          storage_class = "STANDARD_IA"
        }
      }

      dynamic "transition" {
        for_each = rule.value.tier_to_intelligent_after_days != null ? [1] : []
        content {
          days          = rule.value.tier_to_intelligent_after_days
          storage_class = "INTELLIGENT_TIERING"
        }
      }

      dynamic "transition" {
        for_each = rule.value.tier_to_glacier_ir_after_days != null ? [1] : []
        content {
          days          = rule.value.tier_to_glacier_ir_after_days
          storage_class = "GLACIER_IR"
        }
      }

      dynamic "transition" {
        for_each = rule.value.tier_to_glacier_after_days != null ? [1] : []
        content {
          days          = rule.value.tier_to_glacier_after_days
          storage_class = "GLACIER"
        }
      }

      dynamic "transition" {
        for_each = rule.value.tier_to_deep_archive_after_days != null ? [1] : []
        content {
          days          = rule.value.tier_to_deep_archive_after_days
          storage_class = "DEEP_ARCHIVE"
        }
      }

      dynamic "expiration" {
        for_each = rule.value.delete_after_days != null ? [1] : []
        content {
          days = rule.value.delete_after_days
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}
