# k8s/ — Kubernetes Manifests (Kustomize)

Three-cloud deployment using Kustomize. Single base, three overlays.

## Required Reading

- `docs/technical-guides/part4.md` §15 — deployment topology
- `infrastructure/CLAUDE.md` — IAM/networking each cluster expects

## Folder Structure

```
k8s/
├── base/                            Cloud-agnostic manifests — one folder per service + infrastructure
│   ├── api-gateway/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── configmap.yaml
│   │   └── kustomization.yaml
│   ├── auth-service/
│   ├── ... (one per service)
│   ├── postgres-statefulsets/
│   ├── redis-deployments/
│   ├── qdrant/
│   ├── rabbitmq/
│   └── vllm/
└── overlays/
    ├── gcp/                         Dev: GCS, Artifact Registry, T4 GPU patches
    ├── azure/                       Stage: Blob, ACR, V100, Key Vault CSI
    └── aws/                         Prod: S3, ECR, g4dn.xlarge Spot, Secrets Manager
```

## Base/Overlay Rule

**Base is cloud-agnostic.** No GCP-specific annotations, no AWS-specific ARNs, no Azure-specific identity bindings in `base/`. Everything cloud-specific goes in the overlay.

**Overlays use Kustomize patches**, not duplicated manifests. If GKE needs a different `nodeSelector`, that's a `patchesStrategicMerge` in `overlays/gcp/`, not a copy of `deployment.yaml`.

```yaml
# overlays/gcp/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
patchesStrategicMerge:
  - patches/drug-service-gpu.yaml
configMapGenerator:
  - name: env-config
    literals:
      - CLOUD_PROVIDER=gcp
      - STORAGE_BUCKET_RAW=gs://maisys-data-dev/raw
```

## Naming and Labeling

Every resource gets:

```yaml
metadata:
  labels:
    app.kubernetes.io/name: <service-name>
    app.kubernetes.io/part-of: maisys
    app.kubernetes.io/version: <semver>
    app.kubernetes.io/managed-by: kustomize
```

## Secrets

Never `kind: Secret` with raw values in any manifest. Use:

- GCP: GKE Workload Identity → reads Secret Manager
- Azure: AKS Pod Identity → reads Key Vault via CSI driver
- AWS: EKS IRSA → reads Secrets Manager via External Secrets Operator

Each overlay wires up the right mechanism. Base manifests reference secrets by **name only** (`valueFrom.secretKeyRef.name: jwt-secret`), and the overlay ensures the secret is populated from cloud storage.

## Image References

Base uses placeholder image names:

```yaml
image: REPLACE_ME/auth-service:REPLACE_VERSION
```

Overlays substitute:

```yaml
# overlays/gcp/kustomization.yaml
images:
  - name: REPLACE_ME/auth-service
    newName: us-central1-docker.pkg.dev/maisys-dev/maisys/auth-service
    newTag: 1.2.3
```

## Resource Limits

Every container has `requests` and `limits`. No exceptions.

```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 1000m
    memory: 1Gi
```

## Health Checks

Every service has both:

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /readyz
    port: http
  initialDelaySeconds: 5
  periodSeconds: 5
```

`/healthz` = "process is alive". `/readyz` = "ready to receive traffic" (dependencies are reachable).

## What's NEVER in k8s/

- Raw secret values in any manifest
- Cloud-specific resources in `base/`
- Duplicated manifests across overlays (use patches)
- Containers without resource limits
- Containers without health probes
- `latest` tag on any image
