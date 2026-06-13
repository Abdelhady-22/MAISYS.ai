# ──────────────────────────────────────────────────────────────────────────
# User-assigned managed identity for AKS workloads + GitHub Actions
# ──────────────────────────────────────────────────────────────────────────
# Per the task spec this single identity serves two purposes:
#   1. Mapped to k8s ServiceAccounts via AKS Workload Identity (annotations
#      applied in k8s manifests, not from terraform) — pods assume this
#      identity to call Azure APIs (Key Vault read, etc.).
#   2. Federated with GitHub Actions OIDC so deploy workflows assume the
#      same identity, eliminating long-lived secrets in GitHub.
#
# Consolidating both roles in one identity is unusual — typically you'd
# split deploy-time and runtime identities. If that split is wanted later,
# create a second azurerm_user_assigned_identity here and move the GHA
# federation onto it; the deploy SA role-assignments below would follow.
resource "azurerm_user_assigned_identity" "maisys_workload" {
  name                = "maisys-workload-${var.env}"
  location            = azurerm_resource_group.maisys_stage_rg.location
  resource_group_name = azurerm_resource_group.maisys_stage_rg.name
  tags                = local.common_labels
}

# ──────────────────────────────────────────────────────────────────────────
# Federated credential — GitHub Actions OIDC
# ──────────────────────────────────────────────────────────────────────────
# GitHub Actions presents an OIDC token; Azure validates it against this
# federation; the workflow then assumes the user-assigned identity for the
# duration of the run. The subject pattern scopes this to ONE branch.
#
# To federate additional branches/tags/PRs in future, add more
# azurerm_federated_identity_credential resources with different subjects.
resource "azurerm_federated_identity_credential" "gha_stage" {
  name                = "github-actions-${var.github_branch}"
  resource_group_name = azurerm_resource_group.maisys_stage_rg.name
  parent_id           = azurerm_user_assigned_identity.maisys_workload.id

  audience = ["api://AzureADTokenExchange"]
  issuer   = "https://token.actions.githubusercontent.com"
  subject  = "repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"
}

# ──────────────────────────────────────────────────────────────────────────
# Permissions for the GHA workflow on the AKS cluster
# ──────────────────────────────────────────────────────────────────────────
# Sufficient to run `az aks get-credentials` and apply k8s manifests.
resource "azurerm_role_assignment" "gha_aks_user" {
  scope                = module.aks.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = azurerm_user_assigned_identity.maisys_workload.principal_id
}

# Push images to the registry from CI.
resource "azurerm_role_assignment" "gha_acr_push" {
  scope                = module.acr.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.maisys_workload.principal_id
}
