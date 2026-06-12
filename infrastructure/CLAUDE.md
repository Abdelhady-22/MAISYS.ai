# infrastructure/ — Terraform for Three Clouds

Infrastructure as code for GCP (dev), Azure (stage), and AWS (prod). Each cloud has its own folder with parallel resources.

## Required Reading

- `docs/technical-guides/part4.md` §15 — deployment topology
- `DATA_PLAN.md` §4 — cloud bucket structure and storage tiers
- `REPO_PLAN.md` §3.2 — environment-to-cloud mapping

## Folder Structure

```
infrastructure/
├── modules/                       Reusable Terraform modules (cloud-agnostic interface)
│   ├── kubernetes_cluster/        Managed K8s cluster
│   ├── object_storage/            Bucket with lifecycle policy
│   ├── secret_store/              Secret Manager / Key Vault / Secrets Manager
│   └── container_registry/        Artifact Registry / ACR / ECR
├── gcp/
│   ├── main.tf
│   ├── buckets.tf
│   ├── gke.tf
│   ├── iam.tf
│   ├── artifact_registry.tf
│   └── secret_manager.tf
├── azure/
│   ├── main.tf
│   ├── storage.tf
│   ├── aks.tf
│   ├── key_vault.tf
│   ├── acr.tf
│   └── identity.tf
└── aws/
    ├── main.tf
    ├── s3.tf
    ├── eks.tf
    ├── iam.tf
    ├── ecr.tf
    └── secrets_manager.tf
```

## Three-Cloud Parity Rule

Whatever exists on GCP, must exist on Azure and AWS with the same logical name and same lifecycle. If you add a bucket in `gcp/buckets.tf`, you add the corresponding container in `azure/storage.tf` and S3 bucket in `aws/s3.tf` **in the same PR**.

## State Management

Remote state per cloud:

- GCP: GCS bucket `maisys-tf-state-gcp` (created manually once)
- Azure: Storage account `maisystfstate` (created manually once)
- AWS: S3 bucket `maisys-tf-state-aws` (created manually once)

State locking via the native mechanism per cloud (GCS object lock, Azure Blob lease, DynamoDB for AWS).

## Naming Conventions

| Resource | Pattern | Example |
|---|---|---|
| Buckets | `maisys-<purpose>-<env>` | `maisys-data-dev` |
| Clusters | `maisys-<env>` | `maisys-dev` (GKE), `maisys-stage` (AKS), `maisys-prod` (EKS) |
| Service accounts | `maisys-<role>-<env>` | `maisys-vm-sa-dev` |
| Secrets | `<purpose>-<env>` | `kaggle-api-key-dev`, `jwt-secret-prod` |
| Networks/VPCs | `maisys-net-<env>` | `maisys-net-dev` |
| Container registries | `maisys-<env>` | `maisys-dev` |

All resources tagged with `project=maisys`, `env=<dev|stage|prod>`, `managed_by=terraform`.

## Apply Workflow

Never `terraform apply` without a plan review first.

```bash
cd infrastructure/gcp
terraform init
terraform plan -out=plan.tfplan       # review carefully
terraform apply plan.tfplan
```

For real environments, apply runs through GitHub Actions on a protected branch — never from a developer machine.

## What's NEVER in infrastructure/

- Hard-coded credentials, account numbers, or project IDs (use variables)
- `terraform apply -auto-approve` in production
- Inline service definitions that should be in Kubernetes manifests (use `k8s/` for app deployment, not Terraform)
- Per-environment resources duplicated by hand (use `terraform.tfvars` + workspaces or per-env folders)
- Resources without `lifecycle { prevent_destroy = true }` if they hold data (buckets, databases)

## Modules — Cloud-Agnostic Interface

When you write a Terraform module in `modules/`, expose it via the same variable names regardless of which cloud's resources it wraps. This lets the per-cloud folders consume the modules uniformly:

```hcl
# modules/object_storage/variables.tf — same shape for all three clouds
variable "name" { type = string }
variable "lifecycle_policies" { type = list(object(...)) }
variable "labels" { type = map(string) }

# modules/object_storage/outputs.tf
output "url" { value = ... }       # gs://, https://*.blob..., s3://
output "id" { value = ... }
```

Per-cloud folders pick the right backend implementation.
