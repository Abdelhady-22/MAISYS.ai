# data-pipeline/ — All Data Code

Code that scrapes, downloads, uploads, normalizes, ingests, or fine-tunes on data. None of it runs on developer laptops in production (the only exception is the one-time `upload_local_to_gcs.py`, which is your laptop-to-cloud bridge).

## Required Reading

- `DATA_PLAN.md` (root) — complete data inventory, cloud architecture, upload flows
- `docs/technical-guides/part4.md` — beta training data sources, knowledge graphs, master checklist
- `docs/technical-guides/part6.md` §1–§2 — chunking and embedding patterns

## Cloud-Only Rule

**Every script in this folder reads from and writes to cloud URIs.** The only exception is `cloud/upload_local_to_gcs.py`, which accepts local paths as its `--config` source list. Every other script takes URIs like `gs://...`, `s3://...`, `https://maisys.blob.core.windows.net/...`.

This rule is enforced by the storage adapter in `shared/storage/`:

```python
from shared.storage import StorageClient

client = StorageClient.from_uri("gs://maisys-data-dev/raw/drugs_com/")
async for blob in client.list_prefix("general_pdfs/"):
    data = await client.read_bytes(blob.path)
    # process...
```

## Subfolders

| Subfolder | Purpose |
|---|---|
| `scrapers/` | Your existing scrapers (drugs.com, Mayo, MedlinePlus, Infermedica, EndlessMedical). They run on GCP VMs and write directly to GCS. |
| `downloaders/` | External dataset pulls (HuggingFace, Kaggle, GitHub, Harvard Dataverse) |
| `cloud/` | Storage operations (upload, sync, verify, lifecycle policies) |
| `beta_training/` | Per-source normalizers, merge-and-split, quality checker |
| `ingestion/` | Cloud data → Qdrant / Postgres ingesters |
| `fine_tuning/` | LoRA training, evaluation, push to vLLM |

## Normalizer Contract

All normalizers in `beta_training/normalizers/` follow the same contract — see `beta_training/normalizers/README.md`. Briefly:

- Input: a cloud URI pointing to a raw source (CSV, JSON, JSONL, Parquet)
- Output: a JSONL file in `gs://maisys-data-dev/beta_training/normalized/<source>.jsonl`
- Each record: `{"instruction": str, "input": str, "output": str, "metadata": {"source": str, ...}}`
- Required: emit a manifest entry with input checksum, output checksum, record count
- Required: idempotent — running twice on the same input produces the same output

## Ingester Contract

All ingesters in `ingestion/` follow the same contract:

- Input: a cloud URI (or several)
- Output: writes to one specific store (Postgres for `ddimdl_postgres_ingester.py`, Qdrant for the RAG ingesters)
- Required: records SHA-256 of consumed files in a per-file marker; re-runs skip unchanged
- Required: emit progress to Redis pub/sub channel `ingestion.<source>` (uses `shared/progress`)
- Required: support `--force` to re-ingest unchanged files

## Where Scripts Run

| Script | Where it runs |
|---|---|
| `cloud/upload_local_to_gcs.py` | Your laptops (one-time, only laptop-bound script) |
| `cloud/sync_*.py` | GCP VM, ephemeral |
| `cloud/verify_checksums.py` | GCP VM |
| `scrapers/**` | GCP VM (Phase B), or as Kubernetes Jobs |
| `downloaders/**` | GCP VM (Phase B) |
| `beta_training/normalizers/**` | Kubernetes Job on GCP (cheap CPU) |
| `beta_training/merge_and_split.py` | Kubernetes Job on GCP |
| `ingestion/**` | Kubernetes Job — needs Postgres + Qdrant network access |
| `fine_tuning/**` | GCP VM with GPU attached (T4 for dev, V100/A100 for real runs) |

## Secrets

Scripts that need API keys (Kaggle, HuggingFace) read them from cloud Secret Manager via:

```python
from shared.security import get_secret

kaggle_creds = await get_secret("kaggle-api-key")
```

Never `os.getenv("KAGGLE_KEY")` for production secrets. Env vars are fine for local dev only.

## Idempotency Throughout

Every operation in this folder is idempotent:

- Upload: skip if MD5 matches GCS object's MD5
- Scrape: skip if target object exists in GCS (unless `--force`)
- Normalize: skip if output JSONL exists with matching input checksum
- Ingest: skip if marker shows source's checksum already processed

Idempotency is what lets us re-run any step safely after a partial failure.

## What's NEVER in data-pipeline

- Hard-coded local paths (except `upload_local_to_gcs.py`'s `--config`)
- Direct database connections without going through `shared/storage` or a repository
- Manual credential handling outside `shared/security.get_secret`
- Code that requires a developer laptop to run
- Tests that depend on a live external service (use cassettes / VCR / mocks)
