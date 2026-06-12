# PROGRESS — MAISYS Implementation Tracker

**How to use this file:**
- Find the next `[ ]` task in the current phase. That's your next session.
- After completing a task, change `[ ]` to `[x]` and fill in the commit hash.
- Phase gates (between phases) require human verification — see `YOUR_ROLE.md` §7.
- Task IDs (e.g., `P1-T07a`) are for internal tracking only. They do **not** appear in commit messages.

**Legend:**
- `[ ]` Not started
- `[~]` In progress (someone is actively working on it — set this when you start)
- `[x]` Done (with commit hash)
- `[!]` Blocked (with reason)

---

## Phase 0 — Scaffolding

Scaffolding produced before any Claude Code session. Your role: push to GitHub, configure protection, create branches.

- [x] **P0-T01** Push Stage A scaffolding to `MAISYS.ai` on `main` branch
  - Scope: entire repo root
  - Acceptance: `git status` clean on `main`, structure matches `REPO_PLAN.md` §4
  - Commit: _

- [ ] **P0-T02** Configure GitHub branch protection on `main`, `stage`, `dev`
  - Scope: GitHub web UI
  - Acceptance: PR required on `main` and `stage`; status checks required; linear history
  - Commit: _

- [ ] **P0-T03** Add GitHub Actions secret placeholders (`GCP_SA_KEY`, `AZURE_CREDENTIALS`, `AWS_ROLE_ARN`, `DOCKER_REGISTRY_TOKEN`)
  - Scope: GitHub web UI
  - Acceptance: secret names exist (values filled in Phase 1 after Terraform)
  - Commit: _

- [ ] **P0-T04** Create `dev` and `stage` branches from `main`
  - Scope: git
  - Acceptance: branches visible on GitHub
  - Commit: _

---

## Phase 1 — Foundation + Data Uploads (Weeks 1–2)

The hands-on phase. One-time uploads from your two laptops, then everything moves to the cloud.

### 1A — Local data uploads

- [ ] **P1-T01** Edit `data-pipeline/cloud/laptop1_sources.yaml` on Laptop 1
  - Scope: local file edit (not committed — gitignored)
  - Acceptance: file paths point to your actual drugs.com data locations
  - Required reading: `DATA_PLAN.md` §5.1
  - Commit: _ (no commit — local config)

- [ ] **P1-T02** Implement `data-pipeline/cloud/upload_local_to_gcs.py`
  - Scope: `data-pipeline/cloud/upload_local_to_gcs.py` + tests in `data-pipeline/cloud/tests/`
  - Required reading: `DATA_PLAN.md` §5, `docs/technical-guides/part6.md` §7 (error handling)
  - Acceptance: accepts `--config YAML --parallel N`, resumable, MD5 per file, writes manifest to GCS, tests pass
  - Commit: _

- [ ] **P1-T03** Run Phase A1 on Laptop 1 (drugs.com → GCS)
  - Scope: execution only, no code changes
  - Acceptance: `gs://maisys-data-dev/manifests/phase_a1_manifest.json` exists; ~24,000 files in `gs://maisys-data-dev/raw/drugs_com/`
  - Commit: _ (execution task)

- [ ] **P1-T04** Edit `data-pipeline/cloud/laptop2_sources.yaml` on Laptop 2
  - Scope: local file edit (not committed)
  - Acceptance: file paths point to DDIMDL, MIMIC-III, itachi9604 Kaggle, Mendeley 2023
  - Commit: _

- [ ] **P1-T05** Run Phase A2 on Laptop 2
  - Scope: execution only
  - Acceptance: `gs://maisys-data-dev/manifests/phase_a2_manifest.json` exists; all listed datasets present
  - Commit: _

- [ ] **P1-T06** Upload `kaggle.json` and `hf_token` to GCP Secret Manager
  - Scope: one-time CLI command (`gcloud secrets create kaggle-api-key ...`)
  - Acceptance: `gcloud secrets list` shows `kaggle-api-key` and `hf-token`
  - Commit: _

### 1B — Cloud-native scrapers + downloaders

- [ ] **P1-T07a** Migrate Mayo Clinic scrapers to write to GCS (no local output)
  - Scope: `data-pipeline/scrapers/mayo_clinic/**`
  - Required reading: `docs/technical-guides/part4.md` (data sources), `data-pipeline/CLAUDE.md`
  - Acceptance: all 4 sub-scrapers accept `--output-bucket gs://...`; tests pass with mocked GCS client
  - Commit: _

- [ ] **P1-T07b** Migrate MedlinePlus scrapers to write to GCS
  - Scope: `data-pipeline/scrapers/medlineplus/**`
  - Same pattern as T07a
  - Commit: _

- [ ] **P1-T07c** Migrate Infermedica scraper to write to GCS
  - Scope: `data-pipeline/scrapers/infermedica_scraper.py`
  - Commit: _

- [ ] **P1-T07d** Migrate EndlessMedical scraper to write to GCS
  - Scope: `data-pipeline/scrapers/endlessmedical_scraper.py`, `data-pipeline/scrapers/emaddar_endless_api/`
  - Commit: _

- [ ] **P1-T07e** Implement `data-pipeline/downloaders/download_huggingface_medical.py`
  - Scope: `data-pipeline/downloaders/download_huggingface_medical.py` + tests
  - Acceptance: downloads all 18 HF medical datasets (see `DATA_PLAN.md` §2.2 + §2.3), writes to `gs://maisys-data-dev/beta_training/raw_downloads/huggingface/`
  - Commit: _

- [ ] **P1-T07f** Implement `data-pipeline/downloaders/download_chatdoctor.py`
  - Scope: clone `Kent0n-Li/ChatDoctor` GitHub repo, extract JSON files, upload to GCS
  - Acceptance: HealthCareMagic-100k.json + iCliniq-10k.json in `gs://maisys-data-dev/beta_training/raw_downloads/chatdoctor_github/`
  - Commit: _

- [ ] **P1-T07g** Implement `data-pipeline/downloaders/download_mtsamples_kaggle.py`
  - Scope: download script + Kaggle credential resolution via Secret Manager
  - Acceptance: MTSamples CSV in `gs://maisys-data-dev/beta_training/raw_downloads/mtsamples_kaggle/`
  - Commit: _

- [ ] **P1-T07h** Implement `data-pipeline/downloaders/download_knowledge_graphs.py`
  - Scope: PrimeKG (Dataverse wget) + MIT KG (GitHub clone) + itachi9604 Neo4j (GitHub clone)
  - Acceptance: all three in `gs://maisys-data-dev/knowledge_graphs/`
  - Commit: _

- [ ] **P1-T07i** Implement `data-pipeline/cloud/run_phase_b.sh` orchestrator
  - Scope: bash script that runs scrapers in parallel + downloaders sequentially + writes consolidated manifest
  - Acceptance: single-command Phase B execution
  - Commit: _

- [ ] **P1-T08** Provision GCP VM and run Phase B
  - Scope: VM provisioning + execution
  - Acceptance: `gs://maisys-data-dev/manifests/phase_b_manifest.json` exists; all scrapes + downloads complete
  - Commit: _

### 1C — Cross-cloud replication

- [ ] **P1-T09a** Implement `data-pipeline/cloud/sync_gcs_to_azure.py`
  - Scope: rclone-based sync, parallel transfers, checksum preservation
  - Commit: _

- [ ] **P1-T09b** Implement `data-pipeline/cloud/sync_gcs_to_aws.py`
  - Commit: _

- [ ] **P1-T09c** Implement `data-pipeline/cloud/verify_checksums.py`
  - Scope: read all three manifests, verify cross-cloud parity
  - Acceptance: exits non-zero on any mismatch
  - Commit: _

- [ ] **P1-T10** Run Phase C on GCP VM
  - Scope: execution; deletes VM after
  - Acceptance: `verify_checksums.py` reports all green
  - Commit: _

### 1D — Infrastructure (Terraform)

- [ ] **P1-T11** Implement GCP Terraform (`infrastructure/gcp/`)
  - Scope: GCS buckets, GKE cluster, IAM, Artifact Registry, Secret Manager
  - Required reading: `docs/technical-guides/part4.md` §15, `infrastructure/CLAUDE.md`
  - Commit: _

- [ ] **P1-T12** Apply GCP Terraform
  - Scope: execution only
  - Acceptance: GKE cluster healthy, bucket exists with lifecycle policy
  - Commit: _

- [ ] **P1-T13** Implement Azure Terraform (`infrastructure/azure/`)
  - Scope: Storage account, AKS, Key Vault, ACR, Managed Identity
  - Commit: _

- [ ] **P1-T14** Apply Azure Terraform
  - Commit: _

- [ ] **P1-T15** Implement AWS Terraform (`infrastructure/aws/`)
  - Scope: S3 bucket, EKS, IAM (OIDC for GitHub Actions), ECR, Secrets Manager
  - Commit: _

- [ ] **P1-T16** Apply AWS Terraform
  - Commit: _

### 1E — Shared library foundation

- [ ] **P1-T17** Implement `shared/error_handler/`
  - Scope: base exceptions, FastAPI global handler, `APIResponse` envelope
  - Required reading: `docs/technical-guides/part6.md` §7
  - Acceptance: importable from any service, tests pass
  - Commit: _

- [ ] **P1-T18** Implement `shared/logger/`
  - Scope: structlog setup, request logging middleware, JSON output format
  - Commit: _

- [ ] **P1-T19** Implement `shared/models/` (base SQLAlchemy + pagination)
  - Commit: _

- [ ] **P1-T20** Implement `shared/auth/` (JWT decode + FastAPI dependencies)
  - Required reading: `docs/technical-guides/part2.md` §3
  - Commit: _

- [ ] **P1-T21** Implement `shared/storage/` (multi-cloud GCS/Blob/S3 adapter)
  - Scope: unified `StorageClient` with `read_bytes`, `write_bytes`, `list_prefix`, `exists`, `delete`
  - Acceptance: same interface across all three providers, all tests pass
  - Commit: _

### 1F — auth-service end-to-end

- [ ] **P1-T22** Implement `services/auth-service/` (full)
  - Scope: routes (login, register, refresh, OTP, OAuth), JWT issuance, all tables
  - Required reading: `docs/technical-guides/part3.md` §1, `docs/technical-guides/part5.md` (auth schema)
  - Acceptance: all 12 endpoints documented in Part 3 work end-to-end
  - Commit: _

- [ ] **P1-T23** Verify `docker-compose.yml` brings up all infrastructure
  - Scope: docker-compose.yml + auth-service Dockerfile
  - Acceptance: `docker-compose up --build` brings up Postgres + Redis + Qdrant + RabbitMQ + auth-service; health endpoints respond
  - Commit: _

**Phase 1 → Phase 2 gate:** See `YOUR_ROLE.md` §7.

---

## Phase 2 — Drug-Service Vertical Slice (Weeks 2–4)

Build one full module end-to-end so you have something demoable.

- [ ] **P2-T01** Implement `data-pipeline/ingestion/ddimdl_postgres_ingester.py`
  - Scope: reads DDIMDL CSVs from GCS, loads into drug-service Postgres
  - Commit: _

- [ ] **P2-T02** Implement `data-pipeline/ingestion/drug_rag_ingester.py`
  - Scope: reads Drugs.com PDFs + Mayo drugs + MedlinePlus drugs from GCS, chunks, embeds dual, writes to Qdrant Drug RAG
  - Required reading: `docs/technical-guides/part6.md` §1 (chunking), §2 (embedding)
  - Commit: _

- [ ] **P2-T03** Implement `services/drug-service/` skeleton (routes, models, repository, services)
  - Required reading: `docs/technical-guides/part3.md` §10
  - Commit: _

- [ ] **P2-T04** Implement `shared/llm_client/` (LiteLLM wrapper, retry, circuit breaker, KV cache)
  - Required reading: `docs/technical-guides/part2.md` §5, `docs/technical-guides/part6.md` §5
  - Commit: _

- [ ] **P2-T05** Implement `shared/chunking/` + `shared/embedding/`
  - Commit: _

- [ ] **P2-T06** Implement `shared/concurrent/` (gather_with_limit, batch_processor)
  - Commit: _

- [ ] **P2-T07** Implement `shared/progress/` (Redis pub/sub publisher)
  - Commit: _

- [ ] **P2-T08** Implement RxNorm normalization in drug-service
  - Commit: _

- [ ] **P2-T09** Implement Drug Lookup Agent
  - Required reading: `docs/technical-guides/part3.md` §10.3, `part6.md` §3 (agent pattern)
  - Commit: _

- [ ] **P2-T10** Implement Interaction Agent (Tier 0 DDIMDL + Tier 1 RAG + Tier 2 Drugs.com fallback)
  - Commit: _

- [ ] **P2-T11** Implement Dosage Agent
  - Commit: _

- [ ] **P2-T12** Implement Comparison Agent
  - Commit: _

- [ ] **P2-T13** Implement Pharmacokinetics Agent
  - Commit: _

- [ ] **P2-T14** Implement Alternative Agent
  - Commit: _

- [ ] **P2-T15** Implement Web Search Agent (Drugs.com via Playwright)
  - Commit: _

- [ ] **P2-T16** Implement Drug Acquisition Agent
  - Commit: _

- [ ] **P2-T17** WebSocket progress events for drug-service
  - Commit: _

- [ ] **P2-T18** Visual auto-trigger (chart/diagram/infographic for drug results)
  - Commit: _

- [ ] **P2-T19** Minimal frontend page for drug-service (demo screen)
  - Commit: _

- [ ] **P2-T20** End-to-end test: all 12 drug-service features
  - Scope: integration tests in `tests/integration/drug_service/`
  - Acceptance: all features return sensible output for 10+ test drug pairs
  - Commit: _

**Phase 2 → Phase 3 gate:** See `YOUR_ROLE.md` §7.

---

## Phase 3 — Fan Out (Weeks 4–8)

Other 4 module services + remaining shared library, parallelizable across team.

- [ ] **P3-T01** chatbot-service (full)
- [ ] **P3-T02** symptom-service (full, Alpha pipeline only — Beta deferred to Phase 6)
- [ ] **P3-T03** lab-service (full)
- [ ] **P3-T04** research-service (full, with PDF upload + Paper RAG)
- [ ] **P3-T05** translation-service
- [ ] **P3-T06** safety-service
- [ ] **P3-T07** notification-service
- [ ] **P3-T08** model-router-service
- [ ] **P3-T09** export-service
- [ ] **P3-T10** Cross-service integration tests

---

## Phase 4 — Frontend + Admin + Export (Weeks 7–10)

- [ ] **P4-T01** Frontend skeleton (Vite + React + TS + Tailwind + Redux Toolkit)
- [ ] **P4-T02** i18n setup (Arabic + English) with RTL support
- [ ] **P4-T03** Design system from `docs/frontend-guide/`
- [ ] **P4-T04** Auth pages (login, register, OTP, OAuth callbacks)
- [ ] **P4-T05** Chatbot UI
- [ ] **P4-T06** Drug Agent UI
- [ ] **P4-T07** Symptom Checker UI
- [ ] **P4-T08** Lab Test Explainer UI
- [ ] **P4-T09** Research Paper Assistant UI
- [ ] **P4-T10** Settings + Profile
- [ ] **P4-T11** Admin dashboard (admin-service backend + frontend)
- [ ] **P4-T12** API gateway routing + WebSocket multiplexing

---

## Phase 5 — Three-Cloud Deployment (Weeks 9–12)

- [ ] **P5-T01** k8s base manifests for all 13 services
- [ ] **P5-T02** GCP overlay (dev)
- [ ] **P5-T03** Azure overlay (stage)
- [ ] **P5-T04** AWS overlay (prod)
- [ ] **P5-T05** GitHub Actions deploy workflows
- [ ] **P5-T06** Domain + DNS + TLS
- [ ] **P5-T07** Smoke tests on each environment

---

## Phase 6 — Beta Training Pipeline (Week 10+)

- [ ] **P6-T01** All 20+ normalizers in `data-pipeline/beta_training/normalizers/`
- [ ] **P6-T02** `merge_and_split.py`
- [ ] **P6-T03** `quality_checker.py`
- [ ] **P6-T04** `finetune_lora.py`
- [ ] **P6-T05** `evaluate_model.py`
- [ ] **P6-T06** `push_to_vllm.py`
- [ ] **P6-T07** Symptom-service Beta integration
- [ ] **P6-T08** Triple-consent flow end-to-end

---

## Phase 7 — Monitoring + Operations (Weeks 11–12)

- [ ] **P7-T01** Prometheus configuration
- [ ] **P7-T02** Grafana dashboards (5 dashboards per Part 4 §11)
- [ ] **P7-T03** Loki log aggregation
- [ ] **P7-T04** Alert rules + on-call runbook
- [ ] **P7-T05** Backup & disaster recovery drills
- [ ] **P7-T06** Load testing + performance tuning

---

## Clarifications Log

When an ambiguity is found in the docs and a decision is made, log it here.

_(empty — fill in as decisions are made)_

| Date | Task | Question | Decision | Decided by |
|---|---|---|---|---|
| | | | | |
