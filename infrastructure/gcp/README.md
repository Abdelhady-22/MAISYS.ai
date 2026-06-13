# GCP Terraform — MAISYS dev environment

Manages the GCP dev environment infrastructure: VPC, GKE, Artifact Registry,
Secret Manager, and the IAM plumbing for GitHub Actions Workload Identity
Federation.

State lives in `gs://maisys-tf-state-gcp/gcp/dev/`.

---

## 1. Prerequisites

1. **gcloud authenticated** — both for your CLI session and for terraform:

   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project maisys-dev
   ```

2. **terraform 1.5+ installed** — verify with `terraform version`.

3. **Billing linked** to the GCP project. Without billing, GKE creation fails
   silently in `plan` and loudly in `apply`.

4. **APIs enabled** on the project (one-time):

   ```bash
   gcloud services enable \
       compute.googleapis.com \
       container.googleapis.com \
       artifactregistry.googleapis.com \
       secretmanager.googleapis.com \
       iam.googleapis.com \
       iamcredentials.googleapis.com \
       sts.googleapis.com \
       cloudresourcemanager.googleapis.com \
       --project=maisys-dev
   ```

5. **IAM on your user** — you need at least `roles/owner` (or the equivalent
   bundle: project IAM admin, GKE admin, storage admin, service account admin,
   workload identity pool admin, secret manager admin) to apply this terraform.

---

## 2. Bootstrap — create the state bucket (one-time)

Terraform stores state in a GCS bucket that terraform itself does NOT manage
(chicken-and-egg). Create it once, before the first `terraform init`:

```bash
PROJECT=maisys-dev
gcloud storage buckets create gs://maisys-tf-state-gcp \
    --project="${PROJECT}" \
    --location=us-central1 \
    --uniform-bucket-level-access

# Versioning protects against accidental state loss / corruption.
gcloud storage buckets update gs://maisys-tf-state-gcp --versioning

# Lock down access. Replace OWNER_EMAIL with your account.
gcloud storage buckets add-iam-policy-binding gs://maisys-tf-state-gcp \
    --member="user:OWNER_EMAIL" \
    --role="roles/storage.objectAdmin"
```

Do NOT add the state bucket to terraform — it bootstraps the system.

---

## 3. Terraform import — reconcile existing resources (one-time)

The data bucket and the four secrets already exist (created by hand during
Phase 1 ramp-up). Import them so terraform takes over their lifecycle without
duplicating. Replace `maisys-dev` with your actual project ID if different.

```bash
cd infrastructure/gcp

# 0. Initialize providers + modules (no backend yet — using -backend=false
#    keeps the state bucket out of the loop during validation).
terraform init -backend=false

# 0b. Once you've verified the config parses, re-init with the backend so
#     import writes to remote state.
terraform init

# 1. Data bucket
terraform import \
    'module.data_bucket.google_storage_bucket.this' \
    maisys-data-dev

# 2. Kaggle API key secret
terraform import \
    'module.secret_kaggle_api_key.google_secret_manager_secret.this' \
    projects/maisys-dev/secrets/kaggle-api-key

# 3. Hugging Face token secret
terraform import \
    'module.secret_hf_token.google_secret_manager_secret.this' \
    projects/maisys-dev/secrets/hf-token

# 4. Azure service principal secret (Phase C)
terraform import \
    'module.secret_azure_service_principal.google_secret_manager_secret.this' \
    projects/maisys-dev/secrets/azure-service-principal

# 5. AWS credentials secret (Phase C)
terraform import \
    'module.secret_aws_credentials.google_secret_manager_secret.this' \
    projects/maisys-dev/secrets/aws-credentials
```

After imports, run `terraform plan` and **carefully review every line** of the
diff. Expected diffs for imported resources:

- The bucket may show label additions (`project=maisys`, `env=dev`,
  `managed_by=terraform`) if those weren't applied at hand-create time.
- The secrets will show label additions for the same reason.
- The bucket's `lifecycle_rule` blocks may show drift if the hand-applied
  policy doesn't exactly match the rules in `buckets.tf`. Reconcile either by
  updating the HCL to match what's there, or letting terraform converge the
  policy on `apply`.

No imported resource should show a `replace` or `destroy` action. If it does,
**stop and investigate** before applying — that indicates a mismatch between
the HCL and the real resource that terraform would resolve destructively.

---

## 4. Standard workflow

```bash
cd infrastructure/gcp

# Copy and fill in the example tfvars.
cp terraform.tfvars.example terraform.tfvars
${EDITOR:-vi} terraform.tfvars   # set project_id and github_repo

# Initial run on a clean machine:
terraform init

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

After `terraform apply`, read the federation values and store them as repo
secrets. Both values are non-sensitive on their own — the security boundary
is the `attribute_condition` baked into the provider.

```bash
# From infrastructure/gcp/
WIF_PROVIDER=$(terraform output -raw gha_workload_identity_provider)
DEPLOY_SA=$(terraform output -raw gha_service_account_email)

gh secret set GCP_WIF_PROVIDER --body "${WIF_PROVIDER}" --repo your-org/MAISYS.ai
gh secret set GCP_DEPLOY_SA    --body "${DEPLOY_SA}"    --repo your-org/MAISYS.ai
```

In the GitHub Actions workflow, use these with `google-github-actions/auth`:

```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}
    service_account: ${{ secrets.GCP_DEPLOY_SA }}
```

No service account key file ever leaves GCP.

---

## 6. Teardown — destroy the dev environment

This is destructive and should only be done at end-of-project. The data bucket
and the secrets are protected by `prevent_destroy` and import state — `destroy`
will fail loudly until those are explicitly opted out of.

```bash
cd infrastructure/gcp

# Step 1 — remove the prevent_destroy lifecycle block from the object_storage
# module (modules/object_storage/gcp/main.tf), or use:
terraform state rm 'module.data_bucket.google_storage_bucket.this'
# and then delete the bucket via `gcloud storage buckets delete` manually.

# Step 2 — same for each secret you actually want to delete. Secrets often
# outlive the surrounding infra; review one by one.

# Step 3 — destroy everything else.
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan

# Step 4 — finally, delete the state bucket itself (manual, outside terraform).
gcloud storage rm --recursive gs://maisys-tf-state-gcp
```

---

## File layout

| File | Purpose |
|---|---|
| `main.tf` | Terraform settings, backend, provider, common labels |
| `variables.tf` | Input variables |
| `outputs.tf` | Outputs (GKE info, GHA federation values) |
| `terraform.tfvars.example` | Template for `terraform.tfvars` (gitignored) |
| `network.tf` | VPC + subnet with secondary ranges for pods/services |
| `buckets.tf` | Data bucket (imported) |
| `artifact_registry.tf` | Docker registry |
| `gke.tf` | Regional GKE cluster + default node pool |
| `iam.tf` | Service accounts + Workload Identity Federation for GHA |
| `secret_manager.tf` | Existing secrets, declared for import |

Modules consumed live under `infrastructure/modules/<thing>/gcp/`. Azure and
AWS folders will provide siblings (`modules/<thing>/azure/`, `modules/<thing>/aws/`)
with the same variable shape — see `infrastructure/CLAUDE.md`.
