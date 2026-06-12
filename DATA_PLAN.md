# MAISYS — Final Data Plan (v2)

**Status:** Locked. Ready for execution.
**Repository:** `MAISYS.ai`
**Companion documents:** `REPO_PLAN.md`, `YOUR_ROLE.md`
**Constraint:** Nothing runs locally except one-time data uploads from your two laptops. All other operations run in the cloud. The repository never holds data files.

---

## 1. One-Page Summary

MAISYS data lives in three cloud providers — GCP (dev), Azure (stage), and AWS (prod) — replicated with identical bucket structure. Total static data is **100–180 GB** with **200 GB headroom** per cloud.

Three distinct data flows:

- **Flow 1 — One-time bulk upload (your two laptops → GCP):** Two phases (A1 and A2), one per laptop, each running `data-pipeline/cloud/upload_local_to_gcs.py` to push your already-collected datasets to GCS.
- **Flow 2 — Cloud-native scrape + download (GCP VM → GCS):** A GCP VM runs four scraper scripts (Mayo, MedlinePlus, Infermedica, EndlessMedical) plus all external downloaders (HuggingFace, Kaggle, GitHub, Harvard Dataverse). Outputs land directly in GCS. VM is destroyed after.
- **Flow 3 — Cross-cloud replication (GCP → Azure + AWS):** `rclone`-based sync from a GCP VM, with checksum verification across all three clouds.

After Flow 3 completes, the laptops are **never** the source of truth again. All scripts read from and write to cloud URIs only.

---

## 2. Complete Data Inventory

### 2.1 RAG Knowledge Bases — Production Runtime

These feed the three RAG systems (Drug RAG, Medical RAG, Paper RAG).

| # | Source | Records | Format | Target RAG | Where | How It Gets to Cloud |
|---|---|---|---|---|---|---|
| 1 | Drugs.com general | 17,432 PDFs (~12 GB) | PDF | Drug RAG | **Laptop 1** | Flow 1a |
| 2 | Drugs.com professional | 6,450+ PDFs (~5 GB) | PDF | Drug RAG | **Laptop 1** | Flow 1a |
| 3 | Mayo Clinic — diseases & conditions | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 (script runs on GCP VM) |
| 4 | Mayo Clinic — symptoms | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 |
| 5 | Mayo Clinic — tests & procedures | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 |
| 6 | Mayo Clinic — drugs & supplements | TBD by script | JSON | Drug RAG | **Script on Laptop 2** | Flow 2 |
| 7 | MedlinePlus — health topics | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 |
| 8 | MedlinePlus — drugs | TBD by script | JSON | Drug RAG | **Script on Laptop 2** | Flow 2 |
| 9 | MedlinePlus — lab tests | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 |
| 10 | MedlinePlus — encyclopedia | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 |
| 11 | MedlinePlus — genetics | TBD by script | JSON | Medical RAG | **Script on Laptop 2** | Flow 2 |
| 12 | DDIMDL (DrugBank 5.1.3) | 2 CSVs (572 drugs + 37,264 interactions) | CSV | Drug RAG + Postgres | **Laptop 2** | Flow 1b |

### 2.2 Beta Training — Conversational, Q&A, and Clinical

Converted to JSONL by normalizers in `data-pipeline/beta_training/normalizers/`.

| # | Source | Records | Where | How |
|---|---|---|---|---|
| 13 | Infermedica scrape output | All seed symptoms | **Script on Laptop 2** | Flow 2 (script runs on GCP VM) |
| 14 | EndlessMedical scrape output (incl. emaddar repo) | All feature sessions | **Script on Laptop 2** | Flow 2 |
| 15 | DDIMDL Event.db | (reuse from #12) | — | — |
| 16 | MIMIC-III Clinical Demo (PhysioNet) | 100 patients, 26 tables (~100 MB) | **Laptop 2** | Flow 1b |
| 17 | MTSamples (Kaggle) | ~5,000 records | Kaggle API → cloud VM | Flow 2 (needs your `kaggle.json`) |
| 18 | ChatDoctor HealthCareMagic | 40k of 100k | GitHub clone → cloud VM | Flow 2 |
| 19 | ChatDoctor iCliniq | 10k all | GitHub clone → cloud VM | Flow 2 |
| 20 | MedAlpaca — Medical Flashcards | 33,955 | HuggingFace | Flow 2 |
| 21 | MedAlpaca — Wikidoc Patient Info | 5,942 | HuggingFace | Flow 2 |
| 22 | MedAlpaca — Wikidoc Clinical (sampled) | 5,000 | HuggingFace | Flow 2 |
| 23 | MedAlpaca — StackExchange Health | 7,721 | HuggingFace | Flow 2 |
| 24 | MedAlpaca — StackExchange Biology (filtered) | ~3,000 | HuggingFace | Flow 2 |
| 25 | MedAlpaca — StackExchange Fitness (filtered) | ~2,500 | HuggingFace | Flow 2 |
| 26 | MedAlpaca — StackExchange Bioinformatics (filtered) | ~1,500 | HuggingFace | Flow 2 |
| 27 | MedAlpaca — MEDIQA | 2,208 | HuggingFace | Flow 2 |
| 28 | MedAlpaca — MMMLU (enriched) | 3,787 | HuggingFace | Flow 2 |
| 29 | MedAlpaca — Pubmed Health Advice | 10,178 | HuggingFace | Flow 2 |
| 30 | MedAlpaca — medical_meadow_medqa | Full | HuggingFace | Flow 2 |
| 31 | MedQA-USMLE | ~11,000 | HuggingFace | Flow 2 |
| 32 | MedMCQA | ~193,000 | HuggingFace | Flow 2 |
| 33 | PubMedQA (pqa_artificial) | ~211,000 | HuggingFace | Flow 2 |
| 34 | `kamruzzaman-asif/Diseases_Dataset` | Full | HuggingFace | Flow 2 |

### 2.3 Knowledge Graphs — Beta Training Instruction Pairs

| # | Source | Records | Where | How |
|---|---|---|---|---|
| 35 | Harvard PrimeKG | 17,000+ diseases | Harvard Dataverse `wget` | Flow 2 |
| 36 | MIT Health Knowledge Graph | 157 diseases × 491 symptoms | GitHub: clinicalml/HealthKnowledgeGraph | Flow 2 |
| 37 | itachi9604 Disease-Symptom-dataset (Neo4j-ready) | 41 × 132 | GitHub: itachi9604/Disease-Symptom-dataset | Flow 2 |
| 38 | itachi9604 Disease-Symptom-Description (Kaggle) | Diseases + symptoms + precautions + weights | **Laptop 2** | Flow 1b |
| 39 | Mendeley 2023 Disease and Symptoms | 2 CSVs, 773 × 377, ~246k rows (182 MB) | **Laptop 2** | Flow 1b |

### 2.4 Generated Artifacts — Created by the Pipeline

These don't exist yet. Written into cloud storage by ingestion and training scripts.

| Artifact | Format | Est. Size | Generated By |
|---|---|---|---|
| Medical RAG chunks | JSONL | ~5–10 GB | `data-pipeline/ingestion/medical_rag_ingester.py` |
| Drug RAG chunks | JSONL | ~10–15 GB | `data-pipeline/ingestion/drug_rag_ingester.py` |
| Dual embeddings (MiniLM + PubMedBERT) | Parquet | ~30–50 GB | Ingesters |
| Beta normalized JSONL | JSONL | ~2–3 GB | Normalizers |
| Beta final (train/val/test) | JSONL | ~1 GB | `merge_and_split.py` |
| LoRA adapter weights | safetensors | ~200 MB / run | `finetune_lora.py` |
| Model checkpoints | safetensors | ~14 GB / checkpoint | `finetune_lora.py` |
| Generated exports (TXT/DOCX/PDF) | Various | Variable | `export-service` |
| User uploads | Various | Variable | User actions (production only) |

---

## 3. What's Where, Definitively

### 3.1 Laptop 1 — Drugs.com Data Only

```
Laptop 1 holds:
└── Drugs.com data
    ├── general PDFs            (~17,432 files, ~12 GB)
    └── professional PDFs       (~6,450 files, ~5 GB)

Total: ~17 GB
Upload: Flow 1a (laptop 1 → GCP) — runs once, ~4–8 hours
After upload: Laptop 1 is no longer authoritative for any data
```

### 3.2 Laptop 2 — Mixed Data + All Scripts

```
Laptop 2 holds:

DATA (to be uploaded):
├── DDIMDL                                  (2 CSVs)
├── MIMIC-III Demo                          (26 CSV tables, ~100 MB)
├── itachi9604 Kaggle Disease-Symptom-Description (CSVs)
└── Mendeley 2023 Disease and Symptoms       (2 CSVs, ~182 MB)

SCRIPTS (already in your possession — moved to repo, then run on GCP VM):
├── Mayo Clinic scrapers       (4 parts: diseases, symptoms, tests, drugs)
├── MedlinePlus scrapers       (5 parts: health topics, drugs, lab tests, encyclopedia, genetics)
├── Infermedica scraper
└── EndlessMedical scraper     (+ emaddar/Endless_medical_API helper)

Total data: ~500 MB
Upload: Flow 1b (laptop 2 → GCP) — fast, < 1 hour
Scripts: Committed to repo (data-pipeline/scrapers/), then run on cloud VM in Flow 2
After upload: Laptop 2 is no longer authoritative
```

### 3.3 Cloud-Native — Downloaded and Scraped on GCP VM (Flow 2)

```
GCP VM (e2-standard-4) runs all of this in sequence:

A. Run your scrapers (Mayo, MedlinePlus, Infermedica, EndlessMedical)
   → writes JSON outputs directly to gs://maisys-data-dev/raw/...

B. Run downloaders:
   ├── download_huggingface_medical.py     (all HF datasets including kamruzzaman-asif)
   ├── download_chatdoctor.py              (GitHub clone)
   ├── download_mtsamples_kaggle.py        (needs your kaggle.json from Secret Manager)
   └── download_knowledge_graphs.py        (PrimeKG + MIT KG + itachi9604 Neo4j)

C. VM is destroyed when done

Estimated time: 4–8 hours
Estimated cost: < $2
```

---

## 4. Three-Cloud Storage Architecture

### 4.1 Bucket Names

| Cloud | Environment | Identifier | Region |
|---|---|---|---|
| GCP | dev | `gs://maisys-data-dev/` | `us-central1` |
| Azure | stage | Storage account `maisysstage`, container `maisys-data-stage` | `eastus` |
| AWS | prod | `s3://maisys-data-prod/` | `us-east-1` |

Capacity: **200 GB per cloud headroom**, with budget alert thresholds (not hard caps — object storage is unbounded by default).

### 4.2 Identical Folder Layout on All Three Clouds

```
maisys-data-{env}/
├── raw/                                  ← Original (cold tier)
│   ├── drugs_com/
│   │   ├── general_pdfs/                 ← From Laptop 1
│   │   └── professional_pdfs/            ← From Laptop 1
│   ├── mayo_clinic/                      ← Produced by cloud-run scraper
│   │   ├── diseases_conditions.json
│   │   ├── symptoms.json
│   │   ├── tests_procedures.json
│   │   └── drugs_supplements.json
│   ├── medlineplus/                      ← Produced by cloud-run scraper
│   │   ├── health_topics.json
│   │   ├── drugs.json
│   │   ├── lab_tests.json
│   │   ├── encyclopedia.json
│   │   └── genetics.json
│   ├── ddimdl/                           ← From Laptop 2
│   │   ├── drugs.csv
│   │   └── interactions.csv
│   ├── mimic_iii_demo/                   ← From Laptop 2 (26 CSV tables)
│   ├── infermedica/                      ← Produced by cloud-run scraper
│   ├── endlessmedical/                   ← Produced by cloud-run scraper
│   └── disease_symptom/
│       ├── itachi9604_kaggle/            ← From Laptop 2
│       └── mendeley_2023/                ← From Laptop 2
│
├── beta_training/
│   ├── raw_downloads/                    ← All Flow 2 downloads
│   │   ├── huggingface/
│   │   │   ├── medalpaca/
│   │   │   ├── medqa_usmle/
│   │   │   ├── medmcqa/
│   │   │   ├── pubmedqa/
│   │   │   ├── kamruzzaman_asif/         ← Moved here (not from laptop)
│   │   │   └── chatdoctor_hf/
│   │   ├── chatdoctor_github/
│   │   └── mtsamples_kaggle/
│   ├── normalized/                       ← Per-source JSONL
│   └── final/                            ← train/val/test
│
├── knowledge_graphs/
│   ├── primekg/                          ← Cloud download (Harvard Dataverse)
│   ├── mit_kg/                           ← Cloud download (GitHub)
│   └── itachi9604_neo4j/                 ← Cloud download (GitHub)
│
├── processed/                            ← Standard tier
│   ├── chunks/{drug,medical}/
│   └── embeddings/{drug,medical}/{minilm,pubmedbert}/v{N}/
│
├── models/                               ← Standard tier
│   ├── lora_adapters/beta_v{N}/
│   └── checkpoints/beta_v{N}/
│
├── secrets/                              ← Cloud Secret Manager refs (not stored here)
│   └── (this folder doesn't actually exist — secrets live in GCP Secret Manager,
│        Azure Key Vault, AWS Secrets Manager — services read by reference)
│
├── user_uploads/                         ← Production only
└── exports/                              ← Standard tier, lifecycle to cold after 90d
```

### 4.3 Storage Tiers

| Path | GCP | Azure | AWS | Reason |
|---|---|---|---|---|
| `raw/**` | Coldline | Cool | S3 IA | Written once, rarely re-read after ingestion |
| `beta_training/raw_downloads/**` | Coldline | Cool | S3 IA | Touched only during fine-tuning runs |
| `beta_training/normalized/**` | Standard | Hot | S3 Standard | Read each training run |
| `beta_training/final/**` | Standard | Hot | S3 Standard | Read each training run |
| `knowledge_graphs/**` | Coldline | Cool | S3 IA | Source-of-truth references, rarely re-read |
| `processed/chunks/**` | Standard | Hot | S3 Standard | Re-read on RAG re-ingestion |
| `processed/embeddings/**` | Standard | Hot | S3 Standard | Hot — needed for runtime |
| `models/**` | Standard | Hot | S3 Standard | Loaded by vLLM at service start |
| `user_uploads/**` | Standard | Hot | S3 Standard | Live user data |
| `exports/**` | Standard → Cold after 90d | Hot → Cool after 90d | Standard → IA after 90d | Users download within first week |

---

## 5. Upload Sequence (Phase 1 of PROGRESS.md)

### Phase A — Laptop Uploads (Flow 1)

#### Phase A1 — Laptop 1 → GCP (Drugs.com only)

**Where it runs:** Your Laptop 1
**Script:** `data-pipeline/cloud/upload_local_to_gcs.py`
**Authentication:** `gcloud auth application-default login` (one-time)
**Duration:** 4–8 hours, depending on home internet upload speed
**Resumable:** Yes — interruption is safe, re-run picks up where it left off

```bash
# On Laptop 1, after cloning the repo:
cd MAISYS.ai
gcloud auth application-default login   # one-time
python data-pipeline/cloud/upload_local_to_gcs.py \
    --source /path/to/drugs_com_data \
    --target gs://maisys-data-dev/raw/drugs_com/ \
    --parallel 8
```

Manifest written to `gs://maisys-data-dev/manifests/phase_a1_manifest.json` with MD5 for every file.

#### Phase A2 — Laptop 2 → GCP (DDIMDL, MIMIC, itachi9604 Kaggle, Mendeley)

**Where it runs:** Your Laptop 2
**Script:** Same `upload_local_to_gcs.py` (different source paths)
**Duration:** < 1 hour (small data, ~500 MB total)

```bash
# On Laptop 2, after cloning the repo:
cd MAISYS.ai
gcloud auth application-default login
python data-pipeline/cloud/upload_local_to_gcs.py \
    --config data-pipeline/cloud/laptop2_sources.yaml
```

The config file maps each local folder to its target GCS path:
```yaml
sources:
  - local: /path/to/ddimdl
    target: gs://maisys-data-dev/raw/ddimdl/
  - local: /path/to/mimic_iii_demo
    target: gs://maisys-data-dev/raw/mimic_iii_demo/
  - local: /path/to/itachi9604_kaggle
    target: gs://maisys-data-dev/raw/disease_symptom/itachi9604_kaggle/
  - local: /path/to/mendeley_2023
    target: gs://maisys-data-dev/raw/disease_symptom/mendeley_2023/
```

Manifest written to `gs://maisys-data-dev/manifests/phase_a2_manifest.json`.

### Phase B — Cloud-Native Scrape + Download (Flow 2)

**Where it runs:** A GCP VM (`e2-standard-4`, 4 vCPU, 16 GB RAM)
**Orchestrator:** `data-pipeline/cloud/run_phase_b.sh`
**Duration:** 4–8 hours
**Cost:** < $2

The VM:
1. Pulls latest from `MAISYS.ai` repo
2. Authenticates to GCP (uses VM's attached service account — no keys to manage)
3. Reads Kaggle API key from GCP Secret Manager
4. Runs four scrapers in parallel:
   - `data-pipeline/scrapers/mayo_clinic/` (4 sub-scrapers)
   - `data-pipeline/scrapers/medlineplus/` (5 sub-scrapers)
   - `data-pipeline/scrapers/infermedica_scraper.py`
   - `data-pipeline/scrapers/endlessmedical_scraper.py`
5. Then runs downloaders sequentially:
   - `data-pipeline/downloaders/download_huggingface_medical.py`
   - `data-pipeline/downloaders/download_chatdoctor.py`
   - `data-pipeline/downloaders/download_mtsamples_kaggle.py`
   - `data-pipeline/downloaders/download_knowledge_graphs.py`
6. Writes manifest to `gs://maisys-data-dev/manifests/phase_b_manifest.json`
7. Self-destructs (VM deleted via shutdown script)

### Phase C — Cross-Cloud Replication (Flow 3)

**Where it runs:** Same kind of GCP VM (small, ephemeral)
**Tool:** `rclone` with parallel transfers
**Duration:** 6–12 hours (background)
**Cost:** ~$15–25 one-time (egress out of GCP)

```bash
# On a temporary GCP VM:
./data-pipeline/cloud/sync_gcs_to_azure.py
./data-pipeline/cloud/sync_gcs_to_aws.py
./data-pipeline/cloud/verify_checksums.py
```

`verify_checksums.py` reads all three manifests (`phase_a1`, `phase_a2`, `phase_b`) and confirms every object exists on Azure and AWS with matching checksum.

---

## 6. Data Integrity, Lifecycle, Cost

### 6.1 Checksum Verification

- Phase A1/A2: MD5 per file at upload, stored in GCS object metadata + central manifest.
- Phase B: Each scraper and downloader appends to the manifest as it writes.
- Phase C: Cross-cloud parity check via `verify_checksums.py`.
- Every ingestion script later verifies source checksum before reading.

### 6.2 Idempotent Ingestion

Every ingester records SHA-256 of consumed files. Re-runs skip unchanged files. Forced re-ingestion via `--force`.

### 6.3 Version Pinning

Embeddings and models live under `{name}/v{N}/` paths. Active version named in `model-router-service`'s active config table — switching versions is a config change, never a path overwrite.

### 6.4 Lifecycle Policies

Defined in Terraform under `infrastructure/{gcp,azure,aws}/`:
- Training checkpoints older than 90 days auto-delete (except `production`-tagged)
- Exports → cold tier after 90 days, delete after 365
- Old embedding versions → cold tier after 30 days, delete after 180 if newer version is in production
- Failed multipart uploads cleaned up after 7 days

### 6.5 Cost Estimate (Sustained Monthly)

| Item | GCP | Azure | AWS |
|---|---|---|---|
| 120 GB cold tier | $0.48 | $1.82 | $1.50 |
| 30 GB standard | $0.60 | $0.60 | $0.69 |
| Egress for daily ops | ~$2 | ~$2 | ~$2 |
| **Monthly subtotal** | **~$3.10** | **~$4.40** | **~$4.20** |

Total sustained: **~$12/month**. One-time spend: ~$15 for Phase C egress. Easily covered by your $550 credits.

Real ongoing cost will be GPU compute for fine-tuning + LLM API calls during dev — not storage.

---

## 7. Ironclad Rules

1. The repo never holds data files. `.gitignore` excludes all dataset formats.
2. Every script takes cloud URIs, never local paths (except Phase A1/A2 which are deliberate one-time exceptions).
3. Laptops are authoritative only until Phase A completes. After that, they're optional and can be wiped.
4. All three clouds must hold identical content. Verified after every Phase C.
5. Everything the runtime system reads is versioned (`v1`, `v2`, ...). Promotion is config-driven.
6. Raw user data never leaves its production cloud — only cross-region backups within AWS.
7. **Secrets never live in the repo.** Kaggle API key, OAuth credentials, LLM API keys all live in cloud Secret Manager / Key Vault / Secrets Manager.

---

*End of Data Plan v2. Ready for execution.*
