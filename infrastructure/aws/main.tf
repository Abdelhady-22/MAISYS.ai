terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # State bucket + lock table are bootstrapped manually — see README.md §2.
  backend "s3" {
    bucket         = "maisys-tf-state-aws"
    key            = "aws/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "maisys-tf-state-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region

  # default_tags applies these to every resource the AWS provider creates
  # that supports tags. Saves repeating the same map in every module call.
  default_tags {
    tags = {
      project    = "maisys"
      env        = var.env
      managed_by = "terraform"
    }
  }
}

# Convenience data source — used for IRSA condition keys, ECR registry
# URL construction, and as a sanity check that the right account is in use.
data "aws_caller_identity" "current" {}

locals {
  common_labels = {
    project    = "maisys"
    env        = var.env
    managed_by = "terraform"
  }
}

# Defensive guardrail — every plan / apply warns if the AWS CLI is pointed
# at the wrong account (e.g. dev's, by accident). Doesn't halt the apply,
# but surfaces the mismatch loudly enough to catch before destructive ops.
check "expected_account" {
  assert {
    condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
    error_message = "Wrong AWS account: expected ${var.expected_account_id} but the active credentials are for ${data.aws_caller_identity.current.account_id}. Switch profile and rerun."
  }
}
