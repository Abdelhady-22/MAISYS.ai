# Azure Terraform — MAISYS stage environment

Manages the Azure stage environment: VNet, AKS, Key Vault, ACR, the data
storage account/container, and the IAM plumbing for GitHub Actions
Workload Identity Federation.

State lives at
`https://maisystfstate.blob.core.windows.net/tfstate/terraform.tfstate`.

| Constant | Value |
|---|---|
| Subscription ID | `02287a2b-5c68-4aa1-a851-a58b52b05ccf` |
| Tenant ID | `201c5a81-5e83-4e81-90f1-b61a45057f87` |
| Resource group | `maisys-stage-rg` |
| Region | `eastus` |
| State storage account | `maisystfstate` (separate from data) |
| Data storage account | `maisysstage` |

---

## 1. Prerequisites

1. **Azure CLI authenticated**:

   ```bash
   az login
   az account set --subscription 02287a2b-5c68-4aa1-a851-a58b52b05ccf
   az account show   # verify the right subscription is active
   ```

2. **terraform 1.5+** installed — `terraform version`.

3. **Permissions on the subscription** — at least `Contributor` plus
   `User Access Administrator` (the latter is needed for the role
   assignments terraform creates). `Owner` covers both.

4. **Resource providers registered** (one-time per subscription):

   ```bash
   for ns in \
       Microsoft.ContainerService \
       Microsoft.ContainerRegistry \
       Microsoft.KeyVault \
       Microsoft.Storage \
       Microsoft.Network \
       Microsoft.ManagedIdentity \
       Microsoft.OperationalInsights; do
     az provider register --namespace "$ns" --wait
   done
   ```

5. **Your Azure AD object ID** — needed for the Key Vault access policy:

   ```bash
   az ad signed-in-user show --query id -o tsv
   ```

   Paste it into `terraform.tfvars` as `operator_object_id`.

---

## 2. Bootstrap — create the state storage account (one-time)

The state account is **separate** from the data account so a `terraform
destroy` on the stage environment can never wipe its own state. Create it
once before the first `terraform init`:

```bash
RG="maisys-stage-rg"
LOCATION="eastus"
STATE_ACCOUNT="maisystfstate"
STATE_CONTAINER="tfstate"

# The resource group exists already (imported below). If you're starting
# from scratch, create it first:
#   az group create --name "${RG}" --location "${LOCATION}"

# Storage account dedicated to terraform state.
az storage account create \
    --name "${STATE_ACCOUNT}" \
    --resource-group "${RG}" \
    --location "${LOCATION}" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false

# Enable versioning — protects against accidental state corruption / loss.
az storage account blob-service-properties update \
    --account-name "${STATE_ACCOUNT}" \
    --resource-group "${RG}" \
    --enable-versioning true

# Container for the state blob.
az storage container create \
    --name "${STATE_CONTAINER}" \
    --account-name "${STATE_ACCOUNT}" \
    --auth-mode login
```

Do NOT add the state account to terraform — it bootstraps the system.

---

## 3. Terraform import — reconcile existing resources (one-time)

The resource group, data storage account, and data container were created
by hand during Phase 1 ramp-up. Import them so terraform takes over their
lifecycle without duplicating.

```bash
cd infrastructure/azure

# 0a. Initialize providers + modules without the backend, so syntax / module
#     wiring can be validated first.
terraform init -backend=false
terraform validate

# 0b. Re-init with the backend so imports write to remote state.
terraform init

# 1. Resource group
terraform import \
    azurerm_resource_group.maisys_stage_rg \
    /subscriptions/02287a2b-5c68-4aa1-a851-a58b52b05ccf/resourceGroups/maisys-stage-rg

# 2. Data storage account
terraform import \
    'module.data_bucket.azurerm_storage_account.this' \
    /subscriptions/02287a2b-5c68-4aa1-a851-a58b52b05ccf/resourceGroups/maisys-stage-rg/providers/Microsoft.Storage/storageAccounts/maisysstage

# 3. Data container
terraform import \
    'module.data_bucket.azurerm_storage_container.this' \
    https://maisysstage.blob.core.windows.net/maisys-data-stage
```

After imports, run `terraform plan` and **carefully review every line** of
the diff. Expected diffs for the imported resources:

- The resource group may show tag additions (`project=maisys`, `env=stage`,
  `managed_by=terraform`).
- The storage account may show tag additions, plus `blob_properties` and
  TLS/HTTPS settings if those weren't applied at hand-create time.
- The container may show only tag additions.
- The management policy on the storage account will appear as a new resource
  to create (it didn't exist before). That's expected.

No imported resource should show `replace` or `destroy`. If it does, **stop
and investigate** before applying — that indicates an HCL/reality mismatch
that terraform would resolve destructively.

---

## 4. Standard workflow

```bash
cd infrastructure/azure

# First-time on a clean machine: populate the tfvars.
cp terraform.tfvars.example terraform.tfvars
${EDITOR:-vi} terraform.tfvars   # set operator_object_id and github_repo

# Every change:
terraform fmt -recursive
terraform validate
terraform plan -out=plan.tfplan
# REVIEW THE PLAN. Then:
terraform apply plan.tfplan
```

The plan-then-apply split is non-negotiable per `infrastructure/CLAUDE.md`.
Never `apply` directly from a fresh diff.

---

## 5. GitHub Actions secrets — populate from terraform outputs

After `terraform apply`, configure the workflow to authenticate via OIDC.
The values below are non-sensitive on their own — the security boundary is
the `subject` baked into the federated credential.

```bash
# From infrastructure/azure/
CLIENT_ID=$(terraform output -raw gha_client_id)
TENANT_ID=201c5a81-5e83-4e81-90f1-b61a45057f87
SUBSCRIPTION_ID=02287a2b-5c68-4aa1-a851-a58b52b05ccf

gh secret set AZURE_CLIENT_ID       --body "${CLIENT_ID}"       --repo your-org/MAISYS.ai
gh secret set AZURE_TENANT_ID       --body "${TENANT_ID}"       --repo your-org/MAISYS.ai
gh secret set AZURE_SUBSCRIPTION_ID --body "${SUBSCRIPTION_ID}" --repo your-org/MAISYS.ai
```

In the workflow, use `azure/login` with the OIDC flow:

```yaml
permissions:
  id-token: write       # required for OIDC
  contents: read

steps:
  - uses: azure/login@v2
    with:
      client-id:       ${{ secrets.AZURE_CLIENT_ID }}
      tenant-id:       ${{ secrets.AZURE_TENANT_ID }}
      subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

The federated credential is scoped to the `stage` branch only. PR
deployments or `main` branch deploys must be added as additional
`azurerm_federated_identity_credential` resources with the appropriate
subject patterns (e.g. `repo:OWNER/REPO:environment:production`).

---

## 6. Teardown — destroy the stage environment

This is destructive and should only be done at end-of-project. The resource
group, data storage account, and data container are protected by
`prevent_destroy` blocks and import state — `destroy` will fail loudly
until those are explicitly opted out of.

```bash
cd infrastructure/azure

# Step 1 — remove the imported data resources from terraform state so they
# are not destroyed, OR remove their prevent_destroy blocks and let
# terraform destroy them. For an end-of-project teardown the safer option
# is removing from state first, then deleting the data manually:
terraform state rm 'module.data_bucket.azurerm_storage_container.this'
terraform state rm 'module.data_bucket.azurerm_storage_account.this'
terraform state rm 'azurerm_resource_group.maisys_stage_rg'

# Step 2 — destroy everything else terraform manages.
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan

# Step 3 — manually delete the data resources (irreversible):
az storage container delete --name maisys-data-stage --account-name maisysstage --auth-mode login
az storage account delete   --name maisysstage --resource-group maisys-stage-rg --yes
az group delete             --name maisys-stage-rg --yes

# Step 4 — finally, delete the state account (manual, outside terraform):
az storage account delete --name maisystfstate --resource-group maisys-stage-rg --yes
```

---

## File layout

| File | Purpose |
|---|---|
| `main.tf` | Terraform settings, backend, providers, locals, resource group (imported) |
| `variables.tf` | Input variables |
| `outputs.tf` | Outputs (AKS info, ACR URL, GHA federation values) |
| `terraform.tfvars.example` | Template for `terraform.tfvars` (gitignored) |
| `network.tf` | VNet + AKS subnet |
| `storage.tf` | Data storage account + container (imported) via module |
| `aks.tf` | AKS cluster via module |
| `acr.tf` | Azure Container Registry + AcrPull binding for AKS |
| `key_vault.tf` | Key Vault with access policies for operator, AKS, GHA identity |
| `identity.tf` | User-assigned identity, federated credential for GHA, role assignments |

Modules consumed live under `infrastructure/modules/<thing>/azure/`. GCP
siblings are at `modules/<thing>/gcp/` (P1-T11). AWS folders follow the
same pattern.
