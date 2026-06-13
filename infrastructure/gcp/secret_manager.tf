# Every secret declared here ALREADY EXISTS in Secret Manager and must be
# brought into terraform state via `terraform import`. See README.md §3 for
# the exact import commands.
#
# Secret VERSIONS (the values) are never managed by terraform — they're
# written via gcloud / application code. Keeping versions out of state
# avoids exposing secret material in the state file.

module "secret_kaggle_api_key" {
  source = "../modules/secret_store/gcp"

  name   = "kaggle-api-key"
  labels = local.common_labels
}

module "secret_hf_token" {
  source = "../modules/secret_store/gcp"

  name   = "hf-token"
  labels = local.common_labels
}

module "secret_azure_service_principal" {
  source = "../modules/secret_store/gcp"

  name   = "azure-service-principal"
  labels = local.common_labels
}

module "secret_aws_credentials" {
  source = "../modules/secret_store/gcp"

  name   = "aws-credentials"
  labels = local.common_labels
}
