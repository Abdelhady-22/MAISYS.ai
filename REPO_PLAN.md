# MAISYS — Final Repository Plan (v2)

**Status:** Locked. Ready for execution.
**Repository:** `MAISYS.ai` (GitHub)
**Companion documents:** `DATA_PLAN.md`, `YOUR_ROLE.md`

---

## 1. Repository Philosophy

The MAISYS repo is the **single source of truth for what the system IS** — code, configuration, infrastructure-as-code, documentation, Claude Code working instructions, and the data-pipeline scripts (including your existing scrapers that will run on cloud VMs).

The cloud buckets are the **source of truth for what the system KNOWS** — datasets, embeddings, model weights, generated outputs.

These never mix. The repo never holds data. The cloud never holds code.

---

## 2. Ironclad Rules

1. **No data files in the repo.** `.gitignore` excludes `*.pdf`, `*.csv`, `*.jsonl`, `*.parquet`, `*.db`, `*.safetensors`, etc.
2. **No secrets in the repo.** `.env.example` shows variable names only. Real values live in cloud Secret Manager / Key Vault / Secrets Manager.
3. **Every script takes cloud URIs.** No local-path arguments. (Phase A1/A2 upload scripts are deliberate exceptions — one-time bridge.)
4. **No architecture decisions in code.** All decisions are in `docs/technical-guides/`. Code implements; it does not invent.
5. **No file modification outside the current task's declared scope.** Every Claude Code session declares which files/folders it may write.
6. **No silent doc-code drift.** Conflicts get raised, never silently resolved.
7. **One CLAUDE.md per natural context boundary.** Claude Code walks the directory tree and loads them all — exploit this hierarchy.

---

## 3. Dual-Environment Development Workflow

You have two ways to work:

### 3.1 Primary — Editing on Your Laptop

- Clone `MAISYS.ai` to your laptop (either one)
- Edit code in your preferred editor (VS Code, etc.)
- Use Claude Code locally on your laptop for development sessions
- Push branches to GitHub
- CI/CD on push handles testing + deployment

### 3.2 Secondary — Claude Code on the GCP VM

- The same `MAISYS.ai` repo is cloned on a GCP VM
- You SSH into the VM (or use VS Code Remote SSH) and run Claude Code there
- Same git workflow — pull, work, push
- The VM is where the **data-running** sessions happen (Phase B scrapers, ingestion jobs, training runs) because they need cloud bucket access and possibly GPU

### 3.3 When to Use Which

| Task | Recommended Environment |
|---|---|
| Writing code for a service | Laptop (your editor) |
| Reviewing Claude Code diffs | Laptop |
| Designing a new agent | Laptop |
| Writing tests | Either |
| Running scrapers (Phase B) | GCP VM (needs bucket write access + always-on) |
| Running ingestion (chunking + embedding) | GCP VM (needs cloud bucket + sometimes GPU) |
| Fine-tuning runs | GCP VM with GPU attached |
| Phase A1/A2 uploads | Laptop (one-time only — laptop holds the data) |

### 3.4 Git as the Sync Channel

Both environments stay in sync via Git. Standard flow:

```
# Laptop edit:
git pull
# ... edit, commit ...
git push origin feature/my-task

# Switch to VM:
git pull
# ... run scripts ...
```

No file syncing between laptop and VM directly — Git is the only channel. This eliminates "which version is the real one" confusion.

---

## 4. Complete Repository Tree

```
MAISYS.ai/
│
├── CLAUDE.md                          ← Root: identity, ironclad rules, map
├── PROGRESS.md                        ← Master implementation tracker
├── SESSION_PROTOCOL.md                ← Claude Code session template
├── YOUR_ROLE.md                       ← What you (Abdelhady) do at each step
├── DATA_PLAN.md                       ← Locked data plan (this companion document)
├── REPO_PLAN.md                       ← This document
├── README.md                          ← Project overview, quick-start
├── .gitignore                         ← Strict no-data, no-secrets
├── .env.example                       ← All env vars (names only)
├── .pre-commit-config.yaml            ← Black, ruff, isort, mypy, secret-scan, no-data-files
├── docker-compose.yml                 ← Local dev INSIDE a cloud VM
├── alembic.ini                        ← Referenced by each service for migrations
│
├── docs/                              ← Read-only reference
│   ├── CLAUDE.md
│   ├── frontend-guide/
│   │   └── MAISYS_frontend_design_guide.md
│   └── technical-guides/
│       ├── MAISYS_technical_guide_part1.md
│       ├── MAISYS_technical_guide_part2.md
│       ├── MAISYS_technical_guide_part3.md
│       ├── MAISYS_technical_guide_part4.md
│       ├── MAISYS_technical_guide_part5.md
│       └── MAISYS_technical_guide_part6.md
│
├── services/                          ← 14 microservices
│   ├── CLAUDE.md
│   ├── api-gateway/
│   ├── auth-service/
│   ├── chatbot-service/
│   ├── drug-service/                  ← First vertical slice
│   ├── symptom-service/
│   ├── lab-service/
│   ├── research-service/
│   ├── translation-service/
│   ├── export-service/
│   ├── safety-service/
│   ├── notification-service/
│   ├── model-router-service/
│   └── admin-service/
│   # Each service folder contains:
│   #   CLAUDE.md, routes/, services/, repository/, models/, utils/,
│   #   exceptions/, tests/, main.py, Dockerfile, requirements.txt
│
├── shared/                            ← Shared library
│   ├── CLAUDE.md
│   ├── auth/
│   ├── chunking/
│   ├── concurrent/
│   ├── embedding/
│   ├── error_handler/
│   ├── llm_client/
│   ├── logger/
│   ├── models/
│   ├── progress/
│   ├── rate_limiter/
│   ├── security/
│   └── storage/                       ← Multi-cloud GCS/Blob/S3 adapter
│
├── frontend/
│   ├── CLAUDE.md
│   ├── src/
│   │   ├── pages/                     ← 29 pages
│   │   ├── components/
│   │   ├── store/
│   │   ├── api/
│   │   ├── i18n/
│   │   ├── hooks/
│   │   └── styles/
│   ├── public/
│   ├── Dockerfile
│   ├── package.json
│   └── vite.config.ts
│
├── data-pipeline/                     ← All data-handling code
│   ├── CLAUDE.md
│   │
│   ├── scrapers/                      ← Your existing scrapers (run on GCP VM)
│   │   ├── drugs_com/                 ← Already executed — output on Laptop 1
│   │   │   ├── drugs_general_scraper.py
│   │   │   ├── scraper_professional.py
│   │   │   └── retry_failed_drugs.py
│   │   ├── mayo_clinic/               ← Scripts only — will run on GCP VM
│   │   │   ├── part1_diseases_conditions/scraper.py
│   │   │   ├── part2_symptoms/scraper.py
│   │   │   ├── part3_tests_procedures/scraper.py
│   │   │   └── part4_drugs/scraper.py
│   │   ├── medlineplus/               ← Scripts only — will run on GCP VM
│   │   │   ├── part1_health_topics/scraper.py
│   │   │   ├── part2_drugs/scraper.py
│   │   │   ├── part3_lab_tests/scraper.py
│   │   │   ├── part4_encyclopedia/scraper.py
│   │   │   ├── part5_genetics/scraper.py
│   │   │   └── utils.py
│   │   ├── infermedica_scraper.py     ← Script only — will run on GCP VM
│   │   ├── endlessmedical_scraper.py  ← Script only — will run on GCP VM
│   │   └── emaddar_endless_api/       ← Helper from emaddar repo
│   │
│   ├── downloaders/                   ← External pulls (cloud-native)
│   │   ├── download_huggingface_medical.py   ← All HF datasets + kamruzzaman-asif
│   │   ├── download_chatdoctor.py
│   │   ├── download_mtsamples_kaggle.py      ← Reads kaggle.json from Secret Manager
│   │   ├── download_knowledge_graphs.py      ← PrimeKG + MIT KG + itachi9604 Neo4j
│   │   └── download_orchestrator.py
│   │
│   ├── cloud/                         ← Storage operations
│   │   ├── storage_client.py
│   │   ├── upload_local_to_gcs.py     ← Phase A1/A2: from laptops (only local-path script)
│   │   ├── laptop1_sources.yaml       ← Config: maps Laptop 1 local paths → GCS targets
│   │   ├── laptop2_sources.yaml       ← Config: maps Laptop 2 local paths → GCS targets
│   │   ├── sync_gcs_to_azure.py       ← Phase C
│   │   ├── sync_gcs_to_aws.py         ← Phase C
│   │   ├── verify_checksums.py        ← Cross-cloud parity check
│   │   ├── run_phase_b.sh             ← Orchestrates scrapers + downloaders on GCP VM
│   │   └── lifecycle_policies/
│   │       ├── gcp_lifecycle.json
│   │       ├── azure_lifecycle.xml
│   │       └── aws_lifecycle.json
│   │
│   ├── beta_training/
│   │   ├── normalizers/
│   │   │   ├── README.md              ← Normalizer contract
│   │   │   ├── chatdoctor_normalizer.py
│   │   │   ├── medalpaca_normalizer.py
│   │   │   ├── medqa_normalizer.py
│   │   │   ├── medmcqa_normalizer.py
│   │   │   ├── pubmedqa_normalizer.py
│   │   │   ├── kamruzzaman_normalizer.py
│   │   │   ├── infermedica_normalizer.py
│   │   │   ├── endlessmedical_normalizer.py
│   │   │   ├── mtsamples_normalizer.py
│   │   │   ├── mimic_iii_normalizer.py
│   │   │   ├── primekg_normalizer.py
│   │   │   ├── mit_kg_normalizer.py
│   │   │   ├── itachi_neo4j_normalizer.py
│   │   │   ├── itachi_kaggle_normalizer.py
│   │   │   └── mendeley_normalizer.py
│   │   ├── merge_and_split.py
│   │   └── quality_checker.py
│   │
│   ├── ingestion/                     ← Cloud data → Qdrant / Postgres
│   │   ├── drug_rag_ingester.py
│   │   ├── medical_rag_ingester.py
│   │   └── ddimdl_postgres_ingester.py
│   │
│   └── fine_tuning/
│       ├── finetune_lora.py
│       ├── evaluate_model.py
│       └── push_to_vllm.py
│
├── infrastructure/                    ← Terraform — cloud setup
│   ├── CLAUDE.md
│   ├── modules/
│   │   ├── kubernetes_cluster/
│   │   ├── object_storage/
│   │   ├── secret_store/
│   │   └── container_registry/
│   ├── gcp/
│   │   ├── main.tf
│   │   ├── buckets.tf                 ← Includes Secret Manager setup
│   │   ├── gke.tf
│   │   ├── iam.tf
│   │   ├── artifact_registry.tf
│   │   └── secret_manager.tf
│   ├── azure/
│   │   ├── main.tf
│   │   ├── storage.tf
│   │   ├── aks.tf
│   │   ├── key_vault.tf
│   │   ├── acr.tf
│   │   └── identity.tf
│   └── aws/
│       ├── main.tf
│       ├── s3.tf
│       ├── eks.tf
│       ├── iam.tf
│       ├── ecr.tf
│       └── secrets_manager.tf
│
├── k8s/                               ← Kubernetes (Kustomize)
│   ├── CLAUDE.md
│   ├── base/                          ← Cloud-agnostic
│   │   └── (one folder per service + infra)
│   └── overlays/
│       ├── gcp/
│       ├── azure/
│       └── aws/
│
├── monitoring/
│   ├── prometheus/prometheus.yml
│   ├── grafana/dashboards/
│   └── loki/loki-config.yaml
│
├── tests/
│   ├── integration/
│   └── e2e/
│
└── .github/
    └── workflows/
        ├── test-feature.yml
        ├── deploy-gcp.yml
        ├── deploy-azure.yml
        ├── deploy-aws.yml
        └── hotfix-aws.yml
```

---

## 5. CLAUDE.md Hierarchy

Claude Code walks from cwd up to repo root, loading every CLAUDE.md it finds.

| File | Loaded When | Approximate Lines |
|---|---|---|
| `/CLAUDE.md` | Every session | ~150 |
| `/docs/CLAUDE.md` | Working in docs/ | ~30 |
| `/services/CLAUDE.md` | Any service work | ~200 |
| `/services/{name}/CLAUDE.md` | That specific service | ~100 |
| `/shared/CLAUDE.md` | Shared library work | ~120 |
| `/frontend/CLAUDE.md` | Frontend work | ~150 |
| `/data-pipeline/CLAUDE.md` | Data pipeline work | ~180 |
| `/infrastructure/CLAUDE.md` | Terraform work | ~80 |
| `/k8s/CLAUDE.md` | Kubernetes work | ~80 |

Root CLAUDE.md is short. It says what MAISYS is, the seven ironclad rules, a pointer table to docs, and standing user preferences. Anything longer goes in the layer-specific CLAUDE.md.

CLAUDE.md files **point to** docs, never duplicate them. Example:
> "Before non-trivial edits to drug-service, read `/docs/technical-guides/part3.md` §10 and `/docs/technical-guides/part5.md` §1.X."

---

## 6. PROGRESS.md and SESSION_PROTOCOL.md

**PROGRESS.md** mirrors `docs/technical-guides/part4.md` §20 (the Master Implementation Checklist), restructured into the hybrid build order:

```
Phase 0 — Scaffolding (done by Claude before first Claude Code session)
Phase 1 — Foundation + data uploads
Phase 2 — Vertical slice: drug-service end-to-end
Phase 3 — Fan out (other 4 module services + remaining shared lib)
Phase 4 — Frontend + Admin + Export
Phase 5 — Three-cloud deployment
Phase 6 — Beta training pipeline
Phase 7 — Monitoring + Operations
```

Each task: ID, title, declared scope (writable paths), required reading (doc sections), acceptance criteria, status, commit hash.

**SESSION_PROTOCOL.md** is the copy-paste template for every Claude Code session. It standardizes:
- How to start (pull, branch, read PROGRESS.md, read required docs)
- How to operate (stay in scope, ask on ambiguity, write tests with code)
- How to finish (lint, types, tests, update PROGRESS.md, commit, push, PR)
- How to roll back (per-task branch → one-command revert)

---

## 7. Secret Management — How Kaggle API Key (and Others) Are Handled

| Secret | Storage | Read By |
|---|---|---|
| Kaggle API key (`kaggle.json`) | GCP Secret Manager: `secret-kaggle-api-key` | `download_mtsamples_kaggle.py` on the Phase B VM |
| HuggingFace token (optional) | GCP Secret Manager: `secret-hf-token` | `download_huggingface_medical.py` |
| GitHub PAT for private repos (if needed) | GCP Secret Manager: `secret-github-pat` | Phase B downloaders |
| LLM API keys (OpenAI, Anthropic, Gemini) | All three cloud secret stores, per environment | `shared/llm_client/` at service startup |
| OAuth client secrets (Google, Apple) | All three cloud secret stores, per environment | `auth-service` |
| DB passwords | All three cloud secret stores, per environment | Each service |

**You upload each secret once** to GCP Secret Manager via a one-time CLI command. Terraform then syncs them to Azure Key Vault and AWS Secrets Manager via cloud-native replication.

The repo **never** contains a real secret. `.env.example` lists variable names only. Pre-commit hook scans for high-entropy strings and rejects matches.

---

## 8. Branch Strategy and CI/CD

| Branch | Triggers | Target |
|---|---|---|
| `feature/*` | Tests, lint, type check | None |
| `dev` | Tests + build + deploy | GCP (development) |
| `stage` | Tests + build + deploy | Azure (staging) |
| `main` | Tests + build + deploy | AWS (production) |
| `hotfix/*` | Fast-track | AWS (production), then backmerge |

Flow: `feature/* → dev → stage → main`. One Claude Code task = one `feature/*` branch.

---

## 9. Stage A — What Gets Created Before You Start

When you approve, I produce all of these as a downloadable archive:

### Top-level files (13)
1. `CLAUDE.md` — root
2. `PROGRESS.md` — full Phase 0–7 task list with checkboxes
3. `SESSION_PROTOCOL.md` — Claude Code session template
4. `YOUR_ROLE.md` — what you do at each step (the new companion document)
5. `DATA_PLAN.md` — locked data plan
6. `REPO_PLAN.md` — this document
7. `README.md`
8. `.gitignore`
9. `.env.example`
10. `.pre-commit-config.yaml`
11. `docker-compose.yml`
12. `alembic.ini`
13. `LICENSE` (default MIT — change if you prefer something else)

### Per-layer CLAUDE.md files (9)
14–22. `docs/`, `services/`, `shared/`, `frontend/`, `data-pipeline/`, `infrastructure/`, `k8s/`, `monitoring/`, `tests/`

### Empty service stubs (14 × 7 = ~98 placeholders)
Each service folder gets its own CLAUDE.md and empty layered subfolders with `.gitkeep`.

### Empty shared/frontend/data-pipeline/infrastructure/k8s subfolder stubs (~50 placeholders)

### .github/workflows (5 files)
`test-feature.yml`, `deploy-gcp.yml`, `deploy-azure.yml`, `deploy-aws.yml`, `hotfix-aws.yml`

### Two YAML config templates
- `data-pipeline/cloud/laptop1_sources.yaml` (for your Laptop 1 paths)
- `data-pipeline/cloud/laptop2_sources.yaml` (for your Laptop 2 paths)

You'll edit these two YAML files to point to your actual local data paths before running the upload.

**Total: ~27 actual content files + ~150 folder structures with `.gitkeep` placeholders.**

---

## 10. After Stage A — Build Order

```
Phase 0 — Scaffolding push
  P0-T01  You push the Stage A archive contents to MAISYS.ai
  P0-T02  Verify branch protection on dev/stage/main
  P0-T03  Add GitHub Actions secrets

Phase 1 — Foundation + data uploads (weeks 1–2)
  P1-T01  Edit laptop1_sources.yaml on Laptop 1
  P1-T02  Implement data-pipeline/cloud/upload_local_to_gcs.py (Claude Code session)
  P1-T03  Run Phase A1 on Laptop 1 (drugs.com data)
  P1-T04  Edit laptop2_sources.yaml on Laptop 2
  P1-T05  Run Phase A2 on Laptop 2 (DDIMDL + MIMIC + itachi9604 Kaggle + Mendeley)
  P1-T06  Upload kaggle.json to GCP Secret Manager (manual one-time step)
  P1-T07  Implement Phase B scrapers/downloaders (Claude Code sessions)
  P1-T08  Provision GCP VM, run Phase B
  P1-T09  Implement Phase C sync scripts (Claude Code session)
  P1-T10  Run Phase C cross-cloud replication
  P1-T11  Verify checksums match across GCP / Azure / AWS
  P1-T12  Implement infrastructure/gcp Terraform (Claude Code session)
  P1-T13  Apply GCP Terraform — creates buckets, GKE cluster, IAM
  P1-T14  Repeat for Azure (P1-T14a) and AWS (P1-T14b)
  P1-T15  Implement shared/error_handler, logger, models, auth, storage
  P1-T16  Implement auth-service end-to-end
  P1-T17  Verify docker-compose.yml runs all infra services

Phase 2 — Vertical slice: drug-service (weeks 2–4)
  P2-T01  data-pipeline/ingestion/ddimdl_postgres_ingester.py
  P2-T02  data-pipeline/ingestion/drug_rag_ingester.py
  P2-T03  drug-service skeleton
  P2-T04  shared/llm_client (LiteLLM + retry + circuit breaker)
  P2-T05  shared/chunking + shared/embedding
  P2-T06  shared/concurrent
  P2-T07  shared/progress
  P2-T08  drug-service: RxNorm normalization
  P2-T09–T14  Drug Lookup, Interaction, Dosage, Comparison, Pharmacokinetics, Alternative agents
  P2-T15  Web Search Agent (Drugs.com Playwright)
  P2-T16  Drug Acquisition Agent
  P2-T17  WebSocket progress events
  P2-T18  Visual auto-trigger
  P2-T19  Minimal frontend page for drug-service
  P2-T20  Drug-service end-to-end test of all 12 features

Phase 3 — Fan out (weeks 4–8)
Phase 4 — Frontend + Admin + Export (weeks 7–10)
Phase 5 — Three-cloud deployment (weeks 9–12)
Phase 6 — Beta training pipeline (week 10+)
Phase 7 — Monitoring + Operations (weeks 11–12)
```

`YOUR_ROLE.md` breaks down what you (Abdelhady) personally do for each of these tasks — see that document for step-by-step instructions.

---

*End of Repository Plan v2. Ready for execution.*
