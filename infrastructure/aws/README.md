# AWS Terraform — MAISYS production environment

Manages the AWS prod environment: VPC, EKS, ECR (one per service), Secrets
Manager (shells, populated separately), the data S3 bucket, and the IAM
plumbing for GitHub Actions OIDC + EKS IRSA.

State lives at `s3://maisys-tf-state-aws/aws/prod/terraform.tfstate` with
locking on DynamoDB table `maisys-tf-state-lock`.

| Constant | Value |
|---|---|
| Account ID | `522096685539` |
| Region | `us-east-1` |
| AZs | `us-east-1a`, `us-east-1b` |
| VPC CIDR | `10.0.0.0/16` |
| Public subnets | `10.0.0.0/24` (1a), `10.0.1.0/24` (1b) |
| Private subnets | `10.0.10.0/24` (1a), `10.0.11.0/24` (1b) |
| State bucket | `maisys-tf-state-aws` |
| Lock table | `maisys-tf-state-lock` |
| Data bucket | `maisys-data-prod` |

---

## 1. Prerequisites

1. **AWS CLI authenticated** against the prod account:

   ```bash
   aws configure                    # or use SSO
   aws sts get-caller-identity      # must return Account: 522096685539
   ```

2. **terraform 1.5+** installed — `terraform version`.

3. **Permissions on the account** — at least all of these (effectively
   `AdministratorAccess` for first apply, then narrow down):
   - VPC: create/manage VPC, subnets, IGW, NAT, route tables, EIPs
   - EKS: create/manage cluster + node groups
   - EC2: pass IAM role to nodes
   - IAM: create roles, policies, OIDC providers
   - ECR: create repositories
   - S3: read/write the state bucket, read the data bucket
   - DynamoDB: read/write the lock table
   - Secrets Manager: create/describe/tag secrets

4. **Default tags context** — the provider applies
   `project=maisys, env=prod, managed_by=terraform` to every resource that
   supports tags. Resources created outside this terraform should follow
   the same convention.

---

## 2. Bootstrap — state bucket + lock table (one-time)

Both must exist before the first `terraform init`. Terraform itself does
NOT manage them (chicken-and-egg).

```bash
REGION="us-east-1"
STATE_BUCKET="maisys-tf-state-aws"
LOCK_TABLE="maisys-tf-state-lock"

# ── State bucket ────────────────────────────────────────────────────────
aws s3api create-bucket \
    --bucket "${STATE_BUCKET}" \
    --region "${REGION}"
# Note: for regions other than us-east-1, add
#   --create-bucket-configuration LocationConstraint="${REGION}"

aws s3api put-bucket-versioning \
    --bucket "${STATE_BUCKET}" \
    --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
    --bucket "${STATE_BUCKET}" \
    --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-public-access-block \
    --bucket "${STATE_BUCKET}" \
    --public-access-block-configuration \
        'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'

# ── Lock table ──────────────────────────────────────────────────────────
aws dynamodb create-table \
    --table-name "${LOCK_TABLE}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "${REGION}"
```

Wait for the table to reach `ACTIVE`:

```bash
aws dynamodb wait table-exists --table-name "${LOCK_TABLE}"
```

Neither resource is in the terraform config — they're the foundation.

---

## 3. Terraform import — reconcile the existing data bucket (one-time)

The S3 bucket and its three sub-resources exist already. Import them so
terraform takes over their lifecycle without recreating.

```bash
cd infrastructure/aws

# 0a. Initialize providers + modules WITHOUT the backend so syntax /
#     wiring can be validated first.
terraform init -backend=false
terraform validate

# 0b. Re-init with the backend so imports write to remote state.
terraform init

# 1. The bucket itself
terraform import \
    'module.data_bucket.aws_s3_bucket.this' \
    maisys-data-prod

# 2. Versioning configuration
terraform import \
    'module.data_bucket.aws_s3_bucket_versioning.this' \
    maisys-data-prod

# 3. Server-side encryption configuration
terraform import \
    'module.data_bucket.aws_s3_bucket_server_side_encryption_configuration.this' \
    maisys-data-prod

# 4. Public access block
terraform import \
    'module.data_bucket.aws_s3_bucket_public_access_block.this' \
    maisys-data-prod
```

All four use the bucket name as the import ID (the AWS provider's convention
for S3 sub-resources).

After imports, run `terraform plan` and **carefully review every line** of
the diff. Expected for the imported resources:

- The bucket may show tag additions (`project`, `env`, `managed_by`) if
  those weren't on it at hand-create time.
- The encryption config will reconcile to AES256 if it was already AES256.
- The lifecycle configuration (`aws_s3_bucket_lifecycle_configuration`)
  appears as a NEW resource to CREATE — it didn't exist on the bucket
  before. That's expected, but **verify the target lifecycle matches what
  the GCP and Azure buckets use** before applying.

No imported resource should show `replace` or `destroy`. If it does,
**stop** — that indicates an HCL/reality mismatch that terraform would
resolve destructively.

---

## 4. Standard workflow

```bash
cd infrastructure/aws

# First-time on a clean machine: populate the tfvars.
cp terraform.tfvars.example terraform.tfvars
${EDITOR:-vi} terraform.tfvars   # set github_repo

# Every change:
terraform fmt -recursive
terraform validate
terraform plan -out=plan.tfplan
# REVIEW THE PLAN. Then:
terraform apply plan.tfplan
```

The plan-then-apply split is non-negotiable per
`infrastructure/CLAUDE.md`. Production deploys especially run through a
protected GitHub Actions branch — not from a developer machine.

---

## 5. GitHub Actions secrets — populate from terraform outputs

After `terraform apply`, configure the workflow to authenticate via OIDC.
The role ARN and account ID are non-sensitive — the security boundary is
the `sub` condition baked into the deploy role's trust policy.

```bash
# From infrastructure/aws/
ROLE_ARN=$(terraform output -raw gha_role_arn)
ACCOUNT_ID=522096685539

gh secret set AWS_ACCOUNT_ID      --body "${ACCOUNT_ID}" --repo your-org/MAISYS.ai
gh secret set AWS_DEPLOY_ROLE_ARN --body "${ROLE_ARN}"   --repo your-org/MAISYS.ai
```

In the workflow:

```yaml
permissions:
  id-token: write       # required for OIDC
  contents: read

steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
      aws-region:     us-east-1
```

The role's trust policy is scoped to `refs/heads/main` only. PR builds,
tags, and other branches will FAIL to assume the role — by design. To
federate additional refs, add more conditions or split into additional
roles in `iam.tf`.

### Populate Secrets Manager values

Terraform creates only the secret SHELLS. After apply, populate each
value:

```bash
aws secretsmanager put-secret-value \
    --secret-id jwt-secret \
    --secret-string "$(openssl rand -base64 48)"

aws secretsmanager put-secret-value \
    --secret-id llm-openai-api-key \
    --secret-string "sk-..."

# etc. for each secret in var.secret_names
```

Values are NEVER committed to terraform — they live only in Secrets Manager.

### Annotate Kubernetes ServiceAccounts with IRSA roles

For each service, annotate the matching k8s ServiceAccount with its IRSA
role. Get the ARN map:

```bash
terraform output -json irsa_role_arns
```

In the k8s manifest:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api-gateway
  namespace: maisys
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::522096685539:role/maisys-irsa-api-gateway-prod
```

The IRSA roles ship with empty permissions on purpose. Add the specific
managed policies / inline policies each service needs in follow-up PRs.

---

## 6. Teardown — destroy the production environment

This is destructive and should only be done at end-of-project. The data
bucket, all four sub-resources, are protected by `prevent_destroy` blocks
and import state. Secrets have a 7-day recovery window.

```bash
cd infrastructure/aws

# Step 1 — remove imported data resources from terraform state so they
# survive the destroy:
terraform state rm 'module.data_bucket.aws_s3_bucket.this'
terraform state rm 'module.data_bucket.aws_s3_bucket_versioning.this'
terraform state rm 'module.data_bucket.aws_s3_bucket_server_side_encryption_configuration.this'
terraform state rm 'module.data_bucket.aws_s3_bucket_public_access_block.this'
# Also remove the lifecycle config we CREATED on the existing bucket:
terraform state rm 'module.data_bucket.aws_s3_bucket_lifecycle_configuration.this'

# Step 2 — destroy everything else terraform manages.
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan

# Step 3 — if you also want the data bucket gone (irreversible):
aws s3 rm s3://maisys-data-prod --recursive
aws s3api delete-bucket --bucket maisys-data-prod

# Step 4 — finally, delete state and lock (manual, outside terraform):
aws s3 rm s3://maisys-tf-state-aws --recursive
aws s3api delete-bucket --bucket maisys-tf-state-aws
aws dynamodb delete-table --table-name maisys-tf-state-lock
```

Secrets Manager secrets enter a recovery window when deleted by terraform
destroy. To purge them immediately:

```bash
for s in $(terraform output -json | jq -r '...'); do
  aws secretsmanager delete-secret --secret-id "$s" --force-delete-without-recovery
done
```

---

## File layout

| File | Purpose |
|---|---|
| `main.tf` | terraform block, S3+DynamoDB backend, provider with default_tags, caller-identity data source |
| `variables.tf` | Input variables incl. services + secret_names lists |
| `outputs.tf` | Outputs (EKS, ECR, GHA role, account ID, IRSA arn map) |
| `terraform.tfvars.example` | Template for `terraform.tfvars` (gitignored) |
| `network.tf` | VPC + 4 subnets + IGW + NAT + route tables |
| `s3.tf` | Data bucket (imported) via object_storage module |
| `ecr.tf` | 14 ECR repos via container_registry module + for_each |
| `eks.tf` | EKS cluster + node group via kubernetes_cluster module |
| `iam.tf` | GHA OIDC + GHA deploy role + 14 IRSA roles via for_each |
| `secrets.tf` | Secret shells via secret_store module + for_each |

Modules consumed live under `infrastructure/modules/<thing>/aws/`. GCP and
Azure siblings sit beside them at `modules/<thing>/gcp/` and
`modules/<thing>/azure/`.
