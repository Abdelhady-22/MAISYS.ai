# MAISYS — Technical Development Guide
## Part 4: Beta Training Pipeline · Frontend · Deployment · Operations · Security · Master Checklist

---

## Table of Contents

1. [Beta Training Data Sources — All 20 Sources](#1-beta-training-data-sources--all-20-sources)
2. [Data Normalization — Unified JSONL Format](#2-data-normalization--unified-jsonl-format)
3. [Beta Training Pipeline — Step by Step](#3-beta-training-pipeline--step-by-step)
4. [Fine-Tuning Pipeline](#4-fine-tuning-pipeline)
5. [Frontend Architecture — 28 Pages](#5-frontend-architecture--28-pages)
6. [Deployment — GCP Testing Environment](#6-deployment--gcp-testing-environment)
7. [Deployment — Azure Production Environment](#7-deployment--azure-production-environment)
8. [Cloud Portability and Switching](#8-cloud-portability-and-switching)
9. [Kubernetes Architecture](#9-kubernetes-architecture)
10. [CI/CD Pipeline — GitHub Actions](#10-cicd-pipeline--github-actions)
11. [Monitoring and Observability](#11-monitoring-and-observability)
12. [Logging Strategy](#12-logging-strategy)
13. [Rate Limiting and Timeouts](#13-rate-limiting-and-timeouts)
14. [Scaling Strategy](#14-scaling-strategy)
15. [Backup and Recovery](#15-backup-and-recovery)
16. [Security Architecture](#16-security-architecture)
17. [Data Privacy and User Data Handling](#17-data-privacy-and-user-data-handling)
18. [HIPAA-Aligned Practices](#18-hipaa-aligned-practices)
19. [Beta Data Compliance](#19-beta-data-compliance)
20. [Master Implementation Checklist](#20-master-implementation-checklist)

---

## 1. Beta Training Data Sources — All 20 Sources

The Beta Symptom Checker fine-tuning pipeline draws from 20 distinct data sources. Every source must be normalized to the same unified JSONL format before it can enter the training pipeline. No source is used raw. The table below specifies: what the source contains, record count estimate, format, license, how it is obtained, and which normalizer handles it.

### 1.1 Primary Sources — Already Scripted

| # | Source | Records (est.) | Format | License | Obtained Via | Normalizer |
|---|---|---|---|---|---|---|
| 1 | Infermedica API diagnosis flows | ~15,000 | JSON | Infermedica ToS | `infermedica_scraper.py` | `infermedica_to_beta_training.py` |
| 2 | EndlessMedical feature sessions | ~5,000 | JSON | Public API | `endlessmedical_scraper.py` | `infermedica_to_beta_training.py` |
| 3 | Medical Flashcards (HuggingFace) | ~34,000 | JSON | CC BY 4.0 | `download_medical_datasets.py` | Built into downloader |
| 4 | ChatDoctor HealthCareMagic | ~100,000 | JSON | Research use | `download_medical_datasets.py` | Built into downloader |
| 5 | ChatDoctor iCliniq | ~10,000 | JSON | Research use | `download_medical_datasets.py` | Built into downloader |
| 6 | PubMed Health Advice | ~10,178 | JSON | CC0 | `download_medical_datasets.py` | Built into downloader |
| 7 | StackExchange Health | ~7,721 | JSON | CC BY-SA 4.0 | `download_medical_datasets.py` | Built into downloader |
| 8 | Wikidoc Patient Information | ~5,942 | JSON | CC BY 3.0 | `download_medical_datasets.py` | Built into downloader |
| 9 | MEDIQA | ~2,208 | JSON | Research use | `download_medical_datasets.py` | Built into downloader |
| 10 | MMMLU Medical | ~3,787 | JSON | Apache 2.0 | `download_medical_datasets.py` | Built into downloader |

### 1.2 Additional Sources — Manual Download + Custom Normalizer

| # | Source | Records (est.) | Format | License | Obtained Via | Normalizer |
|---|---|---|---|---|---|---|
| 11 | MedQA-USMLE | ~11,000 | JSON | CC BY 4.0 | `download_medical_datasets.py` | Built into downloader |
| 12 | MedMCQA | ~193,000 | JSON | Apache 2.0 | `download_medical_datasets.py` | Built into downloader |
| 13 | PubMedQA | ~270,000 | JSON | MIT | `download_medical_datasets.py` | Built into downloader |
| 14 | MedAlpaca Dataset | ~160,000 | JSON | CC BY-NC 4.0 | `download_medical_datasets.py` | Built into downloader |
| 15 | MTSamples (Kaggle) | ~5,000 | CSV | CC0 | Manual Kaggle download | `normalizers/kaggle_normalizer.py` |
| 16 | MIMIC-III Clinical Database Demo | ~100 patients (26 tables) | CSV | ODC-ODbL | Manual PhysioNet download + credentialing | `normalizers/mimic_normalizer.py` |
| 17 | Harvard PrimeKG | ~17,000 diseases | CSV | CC BY 4.0 | `wget https://dataverse.harvard.edu/api/access/datafile/6180626 -O kg.csv` | `normalizers/primekg_normalizer.py` |
| 18 | MIT Health Knowledge Graph | 157 diseases, 491 symptoms | JSON/CSV | MIT | `git clone github.com/clinicalml/HealthKnowledgeGraph` | `normalizers/mit_kg_normalizer.py` |
| 19 | Mendeley Disease & Symptoms 2023 | ~246,000 rows | CSV | CC BY 4.0 | Manual download from Mendeley (DOI: 10.17632/2cxccsxydc.1) | `normalizers/mendeley_normalizer.py` |
| 20 | Kaggle Disease-Symptom Prediction | ~41 diseases × 132 symptoms | CSV | CC BY 4.0 | Manual Kaggle download (`itachi9604/disease-symptom-description-dataset`) | `normalizers/kaggle_normalizer.py` |
| 21 | Diseases Dataset (HuggingFace) | ~246,000 rows | CSV | CC BY 4.0 | `download_medical_datasets.py` | Built into downloader |
| 22 | Consented Beta sessions (GP reviewed) | Grows over time | JSON | Internal — user consented | `beta_review_queue` table in PostgreSQL | Direct SQL export + inline normalizer |

**Note on MIMIC-III:** Full MIMIC-III requires credentialing through PhysioNet (institutional email + training course). The Demo version (100 patients, no free-text notes) is freely available. The Demo is sufficient for the initial training run. Apply for full MIMIC-III access separately for future training runs.

---

## 2. Data Normalization — Unified JSONL Format

Every source, regardless of its original format (CSV, JSON, clinical notes, Q&A pairs), must be converted to one of two unified JSONL formats before entering the training pipeline. All records in the final training file are in one of these two formats — the model sees consistent structure across all sources.

### 2.1 Format A — Single-Turn Instruction

Used for: symptom-to-diagnosis mapping, disease-symptom pairs, medical Q&A, condition explanations.

```jsonl
{"instruction": "A 35-year-old female presents with headache, fever, and fatigue for 2 days. No stiff neck. What are the most likely conditions and appropriate triage level?", "input": "", "output": "The most likely conditions are: (1) Viral infection — most probable given the combination of fever, headache, and fatigue without meningeal signs; (2) Influenza — similar systemic presentation; (3) Tension headache with concurrent viral illness. The absence of neck stiffness significantly reduces concern for bacterial meningitis. Triage recommendation: consultation — the patient should see a doctor within 1-2 days if symptoms persist or worsen. This assessment is educational only. Always consult a qualified healthcare professional.", "metadata": {"source": "infermedica", "format": "single_turn", "triage_level": "consultation"}}
```

### 2.2 Format B — Multi-Turn Conversation

Used for: Infermedica diagnosis flows, EndlessMedical sessions, ChatDoctor conversations, clinical consultation transcripts.

```jsonl
{"messages": [{"role": "system", "content": "You are a medical symptom assessment assistant. Gather symptoms through questions and provide a structured differential diagnosis and triage recommendation. Always recommend professional medical consultation."}, {"role": "user", "content": "I have a headache and fever for two days."}, {"role": "assistant", "content": "I understand. Let me ask a few questions to better understand your symptoms. Do you have any stiffness in your neck?"}, {"role": "user", "content": "No, my neck feels fine."}, {"role": "assistant", "content": "Thank you. Based on your symptoms — headache, fever for two days, without neck stiffness — the most likely conditions are viral infection or influenza. I recommend seeing a doctor within the next 1-2 days if your symptoms do not improve. Please seek emergency care immediately if you develop neck stiffness, severe headache, confusion, or difficulty breathing. This assessment is educational only."}], "metadata": {"source": "infermedica", "format": "multi_turn", "triage_level": "consultation", "turns": 2}}
```

### 2.3 Metadata Fields (Required on Every Record)

Every JSONL record must include a `metadata` object with these fields:

| Field | Type | Values | Required |
|---|---|---|---|
| `source` | string | infermedica, endlessmedical, chatdoctor, medqa, mimic, primekg, mendeley, kaggle, beta_session, etc. | Yes |
| `format` | string | `single_turn` or `multi_turn` | Yes |
| `triage_level` | string | emergency, consultation_24, consultation, self_care, unknown | Yes |
| `age` | integer or null | patient age if available | No |
| `sex` | string or null | male, female, null | No |
| `gp_reviewed` | boolean | true only for Beta consented sessions reviewed by GP | No |
| `language` | string | en (all records must be English at this stage) | Yes |

### 2.4 Normalizer Responsibilities

Each normalizer does exactly five things:
1. Read the source data (CSV, JSON, SQL export, JSONL)
2. Extract relevant fields (chief complaint, symptoms, diagnosis, triage level, conversation turns)
3. Map fields to the unified schema — use null for any field not present in the source
4. Write one JSONL record per case to the output file
5. Log a summary: total records read, records written, records skipped (missing required fields), error count

### 2.5 Source-Specific Notes for Normalizers

**Infermedica flows (`infermedica_to_beta_training.py`):**
Already generates 8 specialized JSONL formats from `diagnosis_flows.json`. These 8 formats are:
- `01_single_turn_diagnosis.jsonl` — symptoms → differential + triage
- `02_multiturn_conversation.jsonl` — full Q&A flow
- `03_reasoning_chain.jsonl` — chain-of-thought: why a diagnosis is likely
- `04_emergency_cases.jsonl` — emergency cases (5× oversampled to balance dataset)
- `05_triage_only.jsonl` — triage classification as standalone skill
- `06_arabic_single_turn.jsonl` — Arabic translated version of single-turn (for future Arabic fine-tuning)
- `07_absent_symptoms.jsonl` — records where absent symptoms change the differential
- `08_endlessmedical_flows.jsonl` — EndlessMedical data in same format

All 8 files are already in the unified format. File 06 (Arabic) is excluded from the current English-only training run.

**MIMIC-III (`mimic_normalizer.py`):**
MIMIC-III is a relational database of 26 CSV tables. The normalizer joins: `ADMISSIONS.csv` (admission info, diagnoses summary), `DIAGNOSES_ICD.csv` (ICD-9 codes), `D_ICD_DIAGNOSES.csv` (ICD code descriptions), `PRESCRIPTIONS.csv` (medications), `LABEVENTS.csv` (lab results summary).

For each unique patient admission: extract the chief complaint (from admission diagnosis field), primary ICD diagnosis, secondary diagnoses, relevant medications, and age/sex. Convert to single-turn format: instruction describes the clinical presentation, output is the diagnosis and triage estimate based on ICD severity coding.

**Harvard PrimeKG (`primekg_normalizer.py`):**
PrimeKG is a knowledge graph with disease nodes and symptom/drug/gene edges. The normalizer extracts disease-symptom relationships. For each disease: build a symptom list from connected symptom nodes. Generate single-turn format: "A patient presents with [symptoms]. What condition is most likely?" — answer is the disease node with its clinical description from the augmented attributes (from Mayo Clinic, Orphanet, DrugBank columns in kg.csv).

**MIT Health Knowledge Graph (`mit_kg_normalizer.py`):**
157 diseases × 491 symptoms. Learned from 270,000 real patient records. The normalizer loads the adjacency data, generates symptom combinations per disease (using the probability weights to create realistic symptom sets), and outputs single-turn format records.

**Mendeley Disease & Symptoms 2023 (`mendeley_normalizer.py`):**
773 diseases, 377 symptoms, ~246,000 rows. Each row has disease name and a set of present symptoms. Normalizer groups rows by disease, creates realistic multi-symptom presentations (preserving the correlation structure), converts to single-turn format.

**MIMIC, PrimeKG, MIT KG records:** These do not have triage levels — the normalizer assigns estimated triage levels based on ICD severity codes (MIMIC), disease acuteness metadata (PrimeKG), or disease category (MIT KG). All triage assignments from these sources are marked `gp_reviewed: false` and flagged for GP review before inclusion.

---

## 3. Beta Training Pipeline — Step by Step

This section defines the exact sequence of operations to build the complete Beta training dataset from all sources. Run these steps in order. Each step's output is the next step's input.

### Step 1 — Infermedica API Scraping

**Script:** `data-pipeline/scrapers/infermedica_scraper.py`
**Requires:** `APP_ID` and `APP_KEY` set at top of file.
**Runtime:** 2–4 hours (full run with all ~1,100 seed symptoms).
**Output:** `data-pipeline/scrapers/output/diagnosis_flows.json` and associated files.
**Quick test:** Set `MAX_SEED_SYMPTOMS = 10` for a 15-minute test run.

### Step 2 — EndlessMedical API Scraping

**Script:** `data-pipeline/scrapers/endlessmedical_scraper.py`
**Requires:** No credentials.
**Runtime:** 1–2 hours.
**Output:** `data-pipeline/scrapers/output_endlessmedical/feature_sessions.json` and `multi_feature_sessions.json`.

### Step 3 — Convert Infermedica + EndlessMedical to JSONL

**Script:** `data-pipeline/beta_training/infermedica_to_beta_training.py`
**Input:** `output/diagnosis_flows.json` + `output_endlessmedical/` directory.
**Output:** `beta_training/` directory with 8 JSONL files.
**Quick test:** `python infermedica_to_beta_training.py --no-arabic --max-records 100`
**Note:** File `06_arabic_single_turn.jsonl` excluded from current English-only training run.

### Step 4 — Download HuggingFace Datasets

**Script:** `data-pipeline/beta_training/download_medical_datasets.py`
**Requires:** Internet connection, ~50GB disk space for all datasets.
**Output:** `beta_training/hf_datasets/` directory, each dataset in its own subdirectory already in unified JSONL format.
**Runtime:** 30–90 minutes depending on connection speed.
**Datasets downloaded:** Medical Flashcards, ChatDoctor (HealthCareMagic + iCliniq), PubMed Health Advice, StackExchange Health, Wikidoc Patient, MEDIQA, MMMLU Medical, MedQA-USMLE, MedMCQA, PubMedQA, MedAlpaca, Diseases Dataset (HuggingFace).

### Step 5 — Manual Dataset Downloads

Download these manually — cannot be automated:

**MTSamples (Kaggle):**
Visit `https://www.kaggle.com/datasets/tboyle10/medicaltranscriptions`. Download `mtsamples.csv`. Place at `data-pipeline/beta_training/raw/mtsamples.csv`.

**MIMIC-III Demo (PhysioNet):**
Visit `https://physionet.org/content/mimiciii-demo/1.4/`. Download all CSV files. Place in `data-pipeline/beta_training/raw/mimic_demo/`.

**Harvard PrimeKG:**
Run: `wget https://dataverse.harvard.edu/api/access/datafile/6180626 -O data-pipeline/beta_training/raw/kg.csv`

**MIT Health Knowledge Graph:**
Run: `git clone https://github.com/clinicalml/HealthKnowledgeGraph data-pipeline/beta_training/raw/mit_kg/`

**Mendeley Disease & Symptoms 2023:**
Visit `https://data.mendeley.com/datasets/2cxccsxydc/1`. Download `Disease and symptoms dataset.csv`. Place at `data-pipeline/beta_training/raw/mendeley_diseases.csv`.

**Kaggle Disease-Symptom Prediction:**
Visit `https://www.kaggle.com/datasets/itachi9604/disease-symptom-description-dataset`. Download all CSV files. Place in `data-pipeline/beta_training/raw/kaggle_disease_symptom/`.

### Step 6 — Run All Normalizers

Run each normalizer script for the manually downloaded sources:

```
python data-pipeline/beta_training/normalizers/mimic_normalizer.py
python data-pipeline/beta_training/normalizers/primekg_normalizer.py
python data-pipeline/beta_training/normalizers/mit_kg_normalizer.py
python data-pipeline/beta_training/normalizers/mendeley_normalizer.py
python data-pipeline/beta_training/normalizers/kaggle_normalizer.py
```

Each normalizer writes its output to `beta_training/normalized/{source_name}.jsonl` and prints a summary: records read, records written, records skipped, errors.

### Step 7 — Export GP-Reviewed Beta Sessions

When GP-reviewed Beta sessions are available (after the platform has been running for some time):

```sql
SELECT unified_record
FROM beta_review_queue
WHERE approved_for_training = true
  AND gp_reviewed = true
  AND withdrawn = false;
```

Export query result to `beta_training/normalized/beta_sessions.jsonl`. Run the inline normalizer to validate schema compliance.

### Step 8 — Merge and Split

**Script:** `data-pipeline/beta_training/merge_and_split.py`

This script:
1. Reads all JSONL files from `beta_training/normalized/` and `beta_training/` (8 Infermedica formats + HuggingFace outputs)
2. Validates every record against the unified schema — records missing required metadata fields are logged and skipped
3. Deduplicates by hashing the instruction + output fields — exact duplicates removed
4. Applies class balance check: no single diagnosis/condition should represent more than 40% of the dataset
5. Applies triage level distribution check: all triage levels must be represented; emergency cases are oversampled to 10% minimum if underrepresented
6. Shuffles the full dataset with a fixed random seed (for reproducibility)
7. Splits: 80% train, 10% validation, 10% test — stratified by triage level

**Output:**
- `beta_training/combined_train.jsonl`
- `beta_training/combined_val.jsonl`
- `beta_training/combined_test.jsonl`
- `beta_training/split_summary.json` — record counts per split, source distribution, triage distribution

### Step 9 — Quality Check

**Script:** `data-pipeline/beta_training/quality_checker.py`

Reads `combined_train.jsonl` and reports:
- Total records
- Records per source (distribution check)
- Triage level distribution
- Emergency case count (warns if below 5% — emergency detection is critical)
- Average instruction length (tokens)
- Average output length (tokens)
- Format A vs Format B ratio
- Any records with null triage_level
- Any records with non-English content detected

Quality gates that block training:
- Total records below 500 → BLOCKED (training with insufficient data produces an unreliable model)
- Emergency cases below 5% of training set → BLOCKED (model must learn emergency detection)
- Any single source above 60% of records → WARNING (class imbalance)
- Triage level completely missing → BLOCKED

Quality gate results printed to console. Training script (`finetune_lora.py`) imports and runs the quality checker before starting — refuses to train if any BLOCKED gate fails.

---

## 4. Fine-Tuning Pipeline

### 4.1 Model Selection Guidance

Three candidate base models for Beta Symptom Checker fine-tuning. The first training run uses one selected model. The selection can be changed for subsequent runs based on evaluation results.

**Meditron-7B** (`epfl-llm/meditron-7b`):
Trained on LLaMA-2 base with additional pre-training on medical guidelines (clinical practice guidelines, medical textbooks). Strong triage reasoning because triage appears explicitly in its pre-training data. Recommended for the first training run — its pre-training domain aligns directly with the symptom checker use case.

**BioMistral-7B** (`BioMistral/BioMistral-7B`):
Trained on Mistral-7B base with PubMed Central pre-training. Strong biomedical knowledge depth but less clinical guideline focus than Meditron. Better choice if the training dataset is heavily weighted toward research-style Q&A (PubMedQA, MedMCQA).

**MedMO-8B-Next** (`MBZUAI/MedMO-8B-Next`):
8B model from MBZUAI with multilingual medical corpus. Slightly better Arabic awareness in its base. Best choice if Arabic fine-tuning is planned for a future run.

### 4.2 LoRA Configuration

LoRA (Low-Rank Adaptation) fine-tunes only a small set of adapter weights while keeping the base model frozen. This dramatically reduces GPU memory requirements and training time while achieving performance close to full fine-tuning.

LoRA parameters:

| Parameter | Value | Meaning |
|---|---|---|
| `r` | 16 | LoRA rank — controls how many adapter parameters are trained. Higher = more capacity, more memory. |
| `lora_alpha` | 32 | Scaling factor. Set to 2× rank for stable training. |
| `target_modules` | `["q_proj", "v_proj"]` | Which attention projection layers receive LoRA adapters. These two cover most of the model's attention mechanism. |
| `lora_dropout` | 0.05 | Dropout on LoRA layers — prevents overfitting. |
| `bias` | `"none"` | Do not train bias terms. Consistent with best practices for LoRA. |
| `task_type` | `"CAUSAL_LM"` | Causal language modeling (next-token prediction). |

### 4.3 Quantization

**8-bit quantization** (`load_in_8bit=True`) is used for all training runs. This halves the model's memory footprint — a 7B model requires approximately 7GB in 8-bit vs 14GB in full float16.

**4-bit quantization** (`load_in_4bit=True`) is available as an alternative if GPU VRAM is severely constrained. It reduces memory further but may affect training stability. Use 8-bit as the default; switch to 4-bit only if a 7B model does not fit in available VRAM with 8-bit.

### 4.4 Training Configuration

| Parameter | Value | Notes |
|---|---|---|
| `num_train_epochs` | 3 | Three passes through the training data. Adjust based on validation loss curve. |
| `per_device_train_batch_size` | 4 | Batch size per GPU. Increase if VRAM allows. |
| `gradient_accumulation_steps` | 4 | Effective batch size = 4 × 4 = 16. Simulates larger batch without extra memory. |
| `learning_rate` | 2e-4 | Standard LoRA learning rate. Reduce to 1e-4 if training loss is unstable. |
| `fp16` | True | Mixed precision training. Reduces memory and speeds up computation. |
| `evaluation_strategy` | `"epoch"` | Evaluate on validation set at end of each epoch. |
| `save_strategy` | `"epoch"` | Save checkpoint at end of each epoch. |
| `load_best_model_at_end` | True | After training completes, load the checkpoint with the best validation loss. |
| `warmup_ratio` | 0.03 | 3% of training steps used for learning rate warmup. |

### 4.5 Training Script Flow

**Script:** `data-pipeline/fine_tuning/finetune_lora.py`

1. Run quality checker on `combined_train.jsonl` — abort if any BLOCKED gate fails
2. Load base model with 8-bit quantization
3. Load tokenizer
4. Apply LoRA configuration via PEFT `get_peft_model()`
5. Load training dataset from `combined_train.jsonl` and validation from `combined_val.jsonl`
6. Initialize `SFTTrainer` (from TRL library)
7. Run training loop — logs loss per step, validation loss per epoch
8. Load best checkpoint after training completes
9. Save LoRA adapter weights to `fine_tuning/output/{model_name}_{timestamp}/adapter/`
10. Save training report to `fine_tuning/output/{model_name}_{timestamp}/training_report.json`

**Expected training time on A100 GPU:** ~4–6 hours for 3 epochs on a 500k record dataset with Meditron-7B at 8-bit.

### 4.6 Model Evaluation

**Script:** `data-pipeline/fine_tuning/evaluate_model.py`

Evaluates the trained model on `combined_test.jsonl` (unseen during training):

**Triage accuracy:** Percentage of test records where the model's triage level output exactly matches the labeled triage level. Target before deployment: ≥ 85%.

**Top-condition accuracy:** Percentage of test records where the model's top-ranked condition matches the labeled primary diagnosis (exact match or acceptable synonym match). Target: ≥ 70%.

**Emergency false negative rate:** Percentage of `emergency`-labeled records where the model output did NOT identify it as an emergency. Target: 0% — the model must never miss an emergency. If this is above 0%, the model is not deployed regardless of other metrics.

**Output:** `evaluation_results_{timestamp}.json` containing all metrics. Evaluation results also written to `beta_training_runs` table in symptom-service PostgreSQL database.

### 4.7 Deployment to vLLM

**Script:** `data-pipeline/fine_tuning/push_to_vllm.py`

1. Verify evaluation results pass all gates (triage accuracy ≥ 85%, emergency false negative = 0%)
2. Merge LoRA adapter weights into the base model: `PeftModel.from_pretrained(base_model, adapter_path).merge_and_unload()`
3. Save merged model to the model storage path accessible by the vLLM server
4. Update `beta_training_runs` table: set `deployed = true` for this run, `deployed = false` for all previous runs
5. Update model-router-service: POST to `/model-router/switch` to update `symptom-service` Beta LLM config to new model
6. vLLM server picks up the new model on its next model reload (scheduled or triggered manually)
7. First Beta session after reload uses the new model automatically

### 4.8 Retraining Triggers

A new training run is initiated when any of these conditions are met:
- 200 or more new GP-approved Beta sessions accumulated since the last training run
- Monthly scheduled check (first Monday of each month) — if any new records since last run, trigger training
- GP team identifies a systematic error pattern in the current deployed model
- Evaluation accuracy score drops below 80% on a spot-check test (indicating distribution shift)

Retraining is always done with the full accumulated dataset (all sources + all new GP-approved sessions), not incrementally. The full dataset is re-split before each training run.

---

## 5. Frontend Architecture — 28 Pages

### 5.1 Technology Stack

| Technology | Version | Purpose |
|---|---|---|
| React | 18 | Component-based UI |
| TypeScript | 5 | Type-safe application logic |
| Tailwind CSS | 3 | Utility-first styling |
| Redux Toolkit | 2 | Global state management |
| Axios | 1.6 | HTTP client with interceptors |
| Native WebSocket API | — | Real-time streaming and progress |
| react-i18next | 14 | Arabic + English i18n |
| react-hot-toast | 2 | Non-blocking notifications |
| file-saver | 2 | Client-side file downloads |
| lucide-react | 0.383 | Icon library |
| Vite | 5 | Build tool |

### 5.2 RTL and Theme Support

**RTL/LTR:** When user selects Arabic, the entire layout switches to RTL. React i18next sets the language. A useRTL hook applies `dir="rtl"` to the root element and flips Tailwind's directional utilities (left/right padding, margin, flex direction). All module UIs adapt — sidebars, progress bars, text alignment, input fields, table columns.

**Light/Dark mode:** A `useTheme` hook reads the user's saved preference from localStorage. A toggle button in the top bar switches between modes. Tailwind's `dark:` prefix is used throughout. The mode is stored in the user's account settings and synced across devices.

### 5.3 WebSocket Architecture

Each module maintains one persistent WebSocket connection per active session. The connection URL format: `wss://api.maisys.x/ws/{session_id}`. The frontend reconnects automatically with exponential backoff if the connection drops. All streaming events (LLM tokens, progress updates, agent activity, visual ready events) arrive through this single connection.

The `useWebSocket` hook manages connection lifecycle, reconnection, and message dispatch. Incoming events are routed by event type to the correct Redux slice for state update.

### 5.4 Complete Page Catalog

#### Public Pages (unauthenticated) — app.maisys.x

**Page 1 — Landing Page** (`/`)
Hero section with MAISYS tagline, animated feature highlights, 5 module cards with brief descriptions and CTA, testimonials or feature stats, CTA to register. Language toggle in navbar. Light/Dark mode toggle.

**Page 2 — About** (`/about`)
What MAISYS is and is not. Mission statement. Technology overview (non-technical). Languages supported. Bilingual display. Safety philosophy.

**Page 3 — How It Works** (`/how-it-works`)
Step-by-step explainer for each module. Visual flowcharts (static SVG, not generated by agents). Explains the two-tier retrieval concept in user-friendly terms ("We search our trusted medical library first, and the web if we need more information").

**Page 4 — Contact / Support** (`/contact`)
Support form (name, email, message, subject). Email contact info. FAQ section for common questions. Links to Privacy Policy and Terms.

**Page 5 — Privacy Policy** (`/privacy`)
Full privacy policy. What data is collected, why, how long it's kept, user rights (access, delete, export). Beta data handling explained separately. Available in Arabic and English.

**Page 6 — Terms of Use** (`/terms`)
Platform terms. Educational use only — not medical advice. User responsibilities. Beta participation terms.

**Page 7 — Login** (`/login`)
Email + password form. Google OAuth button. Apple OAuth button. "Forgot password" link. "Register" link. OTP field appears after correct password entry if OTP is enabled for the account.

**Page 8 — Register** (`/register`)
Email, password, confirm password. Language preference selector. Terms acceptance checkbox. Register button. On submit: email verification OTP sent.

**Page 9 — Forgot Password** (`/forgot-password`)
Email input. "Send reset code" button. Redirects to OTP verification.

**Page 10 — Reset Password** (`/reset-password`)
OTP field + new password + confirm password. Valid only with a valid reset token in URL.

**Page 11 — OTP Verification** (`/verify-otp`)
6-digit OTP input. Resend code button (60-second cooldown). Used for: email verification, login OTP, password reset.

**Page 12 — Email Verification** (`/verify-email`)
Confirmation page shown after clicking email verification link. Auto-redirects to dashboard on success.

#### Authenticated App — Dashboard

**Page 13 — Main Dashboard** (`/dashboard`)
Module selector grid: 5 module cards. Recent activity: last 5 sessions across all modules with timestamps and titles. Quick access: resume last session per module. Health profile completion prompt if profile is empty. Beta participation CTA if eligible and not yet enrolled.

**Page 14 — Profile and Account Settings** (`/settings/profile`)
Name (display name), avatar upload, language preference (Arabic/English), email address (read-only with change option), notification preferences.

**Page 15 — Security Settings** (`/settings/security`)
Password change form. OTP management: enable/disable OTP for login, resend verification. Connected OAuth accounts: Google and Apple, with connect/disconnect. Active sessions list with "Sign out all other devices" option.

**Page 16 — History** (`/history`)
All past sessions across all modules. Filterable by module, date range, keyword search. Each row: module icon, session title, date, status. Click to open session. Bulk delete option.

**Page 17 — Saved Results** (`/saved`)
Sessions bookmarked/starred by the user. Same display as History with star filter. Option to remove bookmark.

**Page 18 — Beta Consent and Settings** (`/settings/beta`)
Three consent gate status indicators (each showing: completed/not completed, timestamp). "Participate in Beta" toggle (Gate 2). If all three gates complete: Beta access enabled indicator. Consent withdrawal button with confirmation dialog. Link to what Beta data is used for.

#### Module Pages

**Page 19 — Medical Chatbot** (`/chatbot`)
Left sidebar: session list with search, new session button. Main area: conversation thread. Input area: text field + voice record button + attach file/image button. Visual Agent Activity collapsible panel (appears during agent runs). Response area: streaming text + citations + visual iframes (charts/infographics/diagrams appearing live). Top bar: session title, share button, export button. Health profile indicator.

**Page 20 — Drug Agent** (`/drugs`)
Tab navigation: 12 feature tabs (Profile, Interactions, Food Interactions, Disease Interactions, Pregnancy, Dosage, Alternatives, Comparison, Pharmacokinetics, Off-Label, Brand/Generic, Drug Class). Each tab has its own input form and results area. Multi-drug input: tag-style chip input with RxNorm auto-complete. Results area: streaming LLM output + visual (auto-triggered charts). Agent Activity panel. Voice input button. Export button per result.

**Page 21 — Symptom Checker Alpha** (`/symptoms`)
Initial form: age, sex (radio), chief complaint (text area), language preference. After submit: conversational interface. Question display area (streaming as the question arrives). Answer input: text field + voice button. Progress indicator: turns 1 of max 8. Current top conditions sidebar (updates after each turn). On finalization: full results view — conditions with probability bars, triage level badge (color-coded), plain-language explanation (streaming), background info section, triage summary. Export button.

**Page 22 — Symptom Checker Beta** (`/symptoms/beta`)
Accessible only after all three consent gates completed. Same UI as Alpha but with prominent BETA warning banner at top that cannot be dismissed. Results display includes "⚠️ BETA — EXPERIMENTAL" watermark. Beta session indicator in the page header.

**Page 23 — Lab Test Explainer** (`/labs`)
Upload area: drag-and-drop zone accepting PDF, JPG, PNG, WEBP, DOCX. File list with processing status per file. After processing: report view — overall urgency badge at top, bar chart of all test values vs reference ranges (auto-generated visual), per-test cards (expandable) each showing: test name, value, status badge, reference range, streaming explanation. Follow-up chat area at the bottom. Export button.

**Page 24 — Research Paper Assistant** (`/research`)
Left sidebar: session list + new session button. Top area: paper workspace — paper list with upload button + "Discover Papers" button. Main area tabs: Chat, Summarize, Translate, Q&A, Compare. Chat tab: same streaming conversation UI as chatbot, paper-scoped. Tool tabs: tool-specific forms with streaming output. Paper discovery: modal dialog showing search results with download/add buttons + pending upload items with links. Share button. Export button.

#### Admin Panel — admin.maisys.x

**Page 25 — Admin Login** (`/login`)
Separate from user auth. Email + password. IP address checked against admin allowlist. MFA required (TOTP authenticator app).

**Page 26 — GP Review Dashboard** (`/review`)
Queue list showing pending Beta sessions for review. Per session: anonymized chief complaint, conversation turns display, Beta model assessment, Beta model triage estimate. Four action buttons: Approve, Correct and Approve (opens correction form), Reject, Flag. Correction form: editable diagnosis and triage level fields + reviewer notes. Queue statistics: pending, approved today, total approved.

**Page 27 — System Monitoring** (`/monitoring`)
Real-time metrics dashboard (auto-refreshing). Panels: request rate per service (line chart), P50/P95/P99 latency per service, error rate per service, active WebSocket connections, LLM call latency by provider, vLLM GPU utilization and memory, RAG retrieval latency (Medical vs Drug), tier 1 vs tier 2 retrieval ratio, RabbitMQ queue depths. Time range selector: last 1h / 6h / 24h / 7d.

**Page 28 — User Management** (`/users`)
Searchable user list. Columns: email, role, registration date, last active, Beta consent status. Actions per user: change role, force email verification, revoke Beta access, deactivate account. Audit log tab showing all admin actions.

**Page 29 — Model Performance Tracker** (`/models`)
Two sections:

Active Model Configuration: table showing current active model per service per role (medical LLM, chart LLM, vision LLM, STT, TTS). Each row has a "Switch Model" button that opens a dropdown of registered models for that role. Switch is instant — no service restart.

Beta Training History: table of all training runs with: date, base model, dataset size, triage accuracy, condition accuracy, emergency false negative rate, deployed status. "View Evaluation Report" link per run. "Deploy This Version" button for approved runs not yet deployed.

---

## 6. Deployment — GCP Development Environment

### 6.1 Purpose

GCP is the **development environment**. Every feature branch merges to `dev` and deploys here. It runs the full MAISYS stack — all 14 services, GPU for vLLM — but with **development data**: test user accounts, partial knowledge base, dev databases that can be reset freely. GCP is where features are validated before promotion to staging. No real user data ever touches GCP.

### 6.2 Data Environment — Dev

| Component | Dev Configuration |
|---|---|
| PostgreSQL | Dev DBs with synthetic test users and test sessions |
| Qdrant | `dev_medical_minilm`, `dev_drug_minilm` etc. — representative subset of full corpus |
| Redis | Can be flushed any time — no critical data |
| DDIMDL | Fully ingested (CSV is fixed size — no cost difference) |
| User accounts | Synthetic test accounts only — no real PII |
| RAG corpus | ~20% of full corpus — enough for all feature tests |

### 6.3 GCP Services Used

| GCP Service | Purpose | Cost Note |
|---|---|---|
| GKE (Google Kubernetes Engine) | Container orchestration | Standard cluster — scale node pool to 0 when idle |
| GPU Node Pool (N1 + T4) | vLLM inference + fine-tuning | Preemptible / Spot GPU — scale to 0 when not testing |
| Cloud Storage (GCS) | Model weights, test exports, training data | Per GB stored |
| Artifact Registry | Docker image storage | Per GB stored |
| Cloud DNS | Dev subdomain (`dev.maisys.x`) | Per zone |
| Cloud Load Balancer | Ingress for GKE | Per forwarding rule |

**Budget management ($300 GCP free credits):** CPU node pool stays on (always needed). GPU node pool is scaled to 0 after each dev session — never leave it running overnight. Use preemptible GPU nodes (up to 80% cheaper). Cloud SQL not used — PostgreSQL runs in-cluster on StatefulSets to avoid per-hour managed DB cost.

### 6.4 GKE Cluster Layout

```
GKE Cluster (us-central1)
│
├── Node Pool: cpu-dev (e2-standard-4, 1 node, autoscale 1–4)
│   ├── All 14 services (1 replica each — dev minimums)
│   ├── postgres (StatefulSet — dev databases)
│   ├── redis (StatefulSet — dev Redis instances)
│   ├── qdrant (StatefulSet — dev RAG collections)
│   └── rabbitmq (StatefulSet)
│
└── Node Pool: gpu-dev (n1-standard-8 + 1x T4, 0–1 nodes, manual scale)
    ├── vllm-server (dev LLM inference)
    └── finetune-job (K8s Job — on demand for training runs)
```

### 6.5 Load Testing on Dev

Run all 6 load test scenarios against GCP before promoting to `stage`. Scenarios use synthetic test data only.

**Scenario 1:** 50 concurrent chatbot sessions, 5 messages each. Target P95 < 8s.
**Scenario 2:** 100 concurrent drug interaction requests (4-drug combos). Target P95 < 45s.
**Scenario 3:** 20 concurrent lab report uploads. Target P95 < 90s.
**Scenario 4:** 200 WebSocket connections held open 10 minutes. Target: zero drops.
**Scenario 5:** vLLM throughput saturation — find max concurrent users before latency exceeds 30s.
**Scenario 6:** 30 concurrent 8-turn Infermedica sessions. All complete within 120s.

Results saved to `load_test_results_{timestamp}.json` and compared against previous baselines.

---

## 7. Deployment — Azure Staging Environment

### 7.1 Purpose

Azure is the **staging environment**. It runs the same code as `dev` but against **production-scale data** — the complete knowledge base, full Qdrant collections, production-volume databases. Azure staging answers one critical question before every release: "Does this code work correctly with real data at real scale?" Bugs that hide under small datasets surface here before reaching real users on AWS.

Promotion to staging happens when:
- All 6 load tests on GCP pass
- The team manually approves the `dev` → `stage` merge
- A full database snapshot from AWS production is available to restore into Azure staging databases

### 7.2 Data Environment — Stage (Production Data)

| Component | Stage Configuration |
|---|---|
| PostgreSQL | Restored from latest AWS production backup — real schema, realistic data volumes |
| Qdrant | Full production collections: all 17,432 Drugs.com PDFs, full DDIMDL, full MedlinePlus + Mayo Clinic |
| Redis | Pre-warmed from production cache snapshots where applicable |
| User accounts | Anonymized snapshot of production user accounts (PII stripped — SHA-256 hashed IDs) |
| RAG corpus | 100% of production corpus — identical to AWS |

**Database refresh cadence:** Azure staging databases are restored from the latest AWS production backup weekly (every Monday at 02:00 UTC) and before every major release. This keeps stage data realistic without being outdated. Restoration uses `pg_restore` from the AWS S3 backup bucket.

### 7.3 Azure Services Used

| Azure Service | Purpose |
|---|---|
| AKS (Azure Kubernetes Service) | Container orchestration — staging |
| Azure Blob Storage | Full model weights, staging exports |
| Azure Container Registry (ACR) | Stage image storage |
| Azure Key Vault | Secrets management (staging secrets — separate from production) |
| Azure DNS | Staging subdomain (`stage.maisys.x`) |
| Azure Load Balancer | Ingress for AKS |
| Azure Monitor | Stage metrics and alerting |
| GPU Node Pool (NC-series — V100) | vLLM with full production models |

**Budget management ($200 Azure credits):** AKS system node pool runs 2 nodes minimum (staging needs HA-like configuration to catch concurrency bugs). GPU node pool scaled to 0 when no active validation. Use Azure Spot Instances for GPU where possible.

### 7.4 AKS Cluster Layout (Stage)

```
AKS Cluster (eastus — staging)
│
├── System Node Pool (Standard_D4s_v3, 2 nodes, autoscale 2–6)
│   ├── All module services (2 replicas each — validates concurrency)
│   ├── All shared services (2 replicas each)
│   ├── postgres (StatefulSet — restored from production snapshot)
│   ├── redis (StatefulSet)
│   ├── qdrant (StatefulSet — full production collections)
│   └── rabbitmq (StatefulSet)
│
└── GPU Node Pool (Standard_NC6s_v3 — V100, 0–1 nodes)
    └── vllm-server (same models as production)
```

### 7.5 Stage Secrets Management

Azure Key Vault stores staging secrets — completely separate vault from production AWS Secrets Manager. Stage secrets: staging database passwords, staging API keys (some services share production keys like Infermedica and RxNorm — these must be the same values as production to properly test API behavior). Mounted via Azure Key Vault CSI Driver.

---

## 8. Deployment — AWS Production Environment

### 8.1 Purpose

AWS is the **production environment**. Only code that has been validated on GCP (dev) and Azure (staging with production data) reaches here. AWS holds the authoritative production databases, the live user accounts, and the full knowledge base that serves real users.

**Budget: $100 AWS free credits.** This requires careful cost management. The production AWS setup is designed to minimize cost for the initial launch while maintaining reliability. The $100 covers approximately the first 2–4 weeks of minimal production traffic depending on usage patterns.

### 8.2 AWS Cost Optimization Plan

The $100 budget is real — every service choice matters.

**Estimated monthly costs at minimum viable production:**

| Service | Tier | Est. Monthly Cost |
|---|---|---|
| EKS Control Plane | Standard | ~$72/month |
| EC2 Worker Nodes | 2× t3.medium (on-demand) | ~$60/month |
| EC2 GPU Node | 1× g4dn.xlarge Spot | ~$20–40/month (variable) |
| S3 | 50GB storage + transfers | ~$5/month |
| ECR | 10GB images | ~$1/month |
| ELB (ALB) | 1 load balancer | ~$16/month |
| Route 53 | 1 hosted zone | ~$0.50/month |
| Data Transfer | Outbound | ~$5/month |
| **Total estimate** | | **~$180/month** |

**The $100 credit covers roughly 2–3 weeks.** Strategy:

1. **EKS Free Tier:** AWS EKS control plane is $0.10/hour = $72/month — unavoidable. Use AWS Free Tier for EC2 instances where possible (750 hours/month of t2.micro/t3.micro free for first 12 months).

2. **GPU on Spot:** Use g4dn.xlarge Spot instances for vLLM. Spot price is typically $0.15–0.25/hour vs $0.526 on-demand. Scale GPU to 0 when not serving real traffic. Use cloud LLMs (GPT-4o, Claude) as primary and fall back to vLLM for local models only.

3. **Route 53 vs Cloudflare:** Keep DNS on Cloudflare (already paid/free tier) — do not replicate to Route 53 unless needed. Save ~$0.50+/month.

4. **Right-size workers:** Start with 2× t3.medium ($0.0416/hour each = ~$60/month). Scale up only when traffic demands it.

5. **Savings plan:** After 1–2 months, convert to 1-year Reserved Instances (saves 30–40%).

### 8.3 AWS Services Used

| AWS Service | Purpose | Free Tier Available |
|---|---|---|
| EKS (Elastic Kubernetes Service) | Container orchestration — production | No ($0.10/hour) |
| EC2 (t3.medium) | CPU worker nodes | Partial (t2.micro free tier — upgrade needed) |
| EC2 (g4dn.xlarge Spot) | GPU node for vLLM | No — use Spot to save 70% |
| S3 | Model weights, production exports, uploaded files, backups | 5GB free, then per-GB |
| ECR (Elastic Container Registry) | Production Docker image storage | 500MB free |
| ALB (Application Load Balancer) | Ingress for EKS | No ($0.008/LCU-hour) |
| AWS Secrets Manager | Production secrets (API keys, DB passwords, JWT secrets) | 30-day trial, then $0.40/secret/month |
| CloudWatch | Metrics and alerting | 10 custom metrics free |
| EBS (Elastic Block Store) | PersistentVolumes for StatefulSets | 30GB free |
| IAM | Service accounts and roles | Always free |

**Alternative to AWS Secrets Manager (to save cost):** Use Kubernetes Secrets with external-secrets-operator pulling from AWS SSM Parameter Store ($0.05/parameter/month — significantly cheaper than Secrets Manager for many secrets).

### 8.4 EKS Cluster Layout (Production)

```
EKS Cluster (us-east-1 — production)
│
├── Node Group: cpu-prod (t3.medium, 2 nodes, autoscale 2–8)
│   ├── All module services (2 replicas each)
│   ├── All shared services (2 replicas each)
│   ├── All infrastructure services
│   ├── postgres (StatefulSet — production databases, EBS gp3 volumes)
│   ├── redis (StatefulSet — production cache)
│   ├── qdrant (StatefulSet — full production knowledge base)
│   └── rabbitmq (StatefulSet)
│
└── Node Group: gpu-prod (g4dn.xlarge Spot, 0–1 nodes)
    └── vllm-server (production LLM inference)
    └── [GPU node scales to 0 when using cloud LLMs only]
```

### 8.5 AWS Secrets Management

Production secrets stored in AWS Secrets Manager OR AWS SSM Parameter Store. EKS accesses secrets via the AWS Secrets and Configuration Provider (ASCP) for Secrets Manager, or Kubernetes external-secrets-operator for SSM Parameter Store. No secret values in Git, Docker images, or Kubernetes manifests.

**IRSA (IAM Roles for Service Accounts):** Each Kubernetes service account is mapped to an AWS IAM role with minimal permissions. The EKS pod receives AWS credentials automatically via the pod's identity — no access keys needed in environment variables.

### 8.6 Production Secrets Strategy

Separate secrets for each environment (dev / stage / production). Production secrets include:
- Database passwords (generated, 40+ char random)
- JWT secret keys (64+ char random)
- All LLM API keys (OpenAI, Anthropic, Google, Groq, etc.)
- Infermedica APP_ID and APP_KEY
- DDIMDL is a static dataset — no API key needed

**Secret rotation:** Rotate database passwords and JWT secrets quarterly. Rotate API keys immediately if any breach is suspected.

### 8.7 Production StorageClass

```yaml
# EBS gp3 storage class for StatefulSets
StorageClass: gp3
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

PostgreSQL PVC: 50GB gp3 per service (expandable). Qdrant PVC: 100GB gp3 (full knowledge base vectors). Redis PVC: 10GB gp3. RabbitMQ PVC: 20GB gp3.

---

## 9. Cloud Portability — Three Clouds, Zero Code Changes

### 9.1 What Changes Between Clouds (Only the Overlay)

Switching between GCP (dev), Azure (stage), and AWS (production) requires no application code changes. Only the Kustomize overlay and CI/CD registry references differ.

| Concern | GCP (dev) | Azure (stage) | AWS (production) |
|---|---|---|---|
| Container Registry | Google Artifact Registry | Azure Container Registry | AWS ECR |
| Object Storage | GCS (`GCSBackend`) | Azure Blob (`AzureBlobBackend`) | S3 (`S3Backend`) |
| Storage env var | `GCS_BUCKET=...` | `AZURE_BLOB_CONTAINER=...` | `AWS_S3_BUCKET=...` |
| Secrets | GCP Secret Manager | Azure Key Vault CSI | AWS Secrets Manager / SSM |
| GPU node label | `cloud.google.com/gke-accelerator: nvidia-tesla-t4` | `accelerator: nvidia-v100` | `k8s.amazonaws.com/accelerator: nvidia-tesla-t4` |
| StorageClass | `standard-rwo` | `managed-premium` | `gp3` |
| Ingress type | GKE Ingress / nginx | AKS nginx | AWS ALB / nginx |
| DNS | Cloud DNS → Cloudflare | Azure DNS → Cloudflare | Route 53 → Cloudflare |

**What is identical across all three:**
- All 14 service Docker images (same build, same binary)
- All service logic, routes, repositories, models
- All database schemas (Alembic migrations)
- All Kubernetes base manifests (`k8s/base/`)
- All Kustomize base configuration
- `shared/storage/storage_client.py` — reads `CLOUD=gcp|azure|aws` and routes to correct backend

### 9.2 Adding the AWS S3 Backend

`shared/storage/storage_client.py` now supports three backends:

```
CLOUD=gcp   → GCSBackend   (google-cloud-storage)
CLOUD=azure → AzureBlobBackend (azure-storage-blob)
CLOUD=aws   → S3Backend    (boto3)
```

The `S3Backend` implements the same `StorageInterface` as the other two:
- `upload(path: str, data: bytes)` → `s3.put_object(Bucket=bucket, Key=path, Body=data)`
- `download(path: str) → bytes` → `s3.get_object(...)`
- `delete(path: str)` → `s3.delete_object(...)`

AWS credentials are provided via IRSA (IAM Role for Service Accounts) — no `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` in environment variables.

### 9.3 Kustomize Overlay Structure

```
k8s/
├── base/
│   ├── deployments/          ← One Deployment per service (all 14)
│   ├── statefulsets/         ← postgres, redis, qdrant, rabbitmq
│   ├── services/             ← ClusterIP services (internal cluster DNS)
│   ├── ingress.yaml          ← Nginx Ingress base config
│   └── configmap-base.yaml   ← Non-sensitive shared config (log level, timeouts, etc.)
│
└── overlays/
    ├── gcp/
    │   ├── kustomization.yaml
    │   ├── configmap-gcp.yaml        ← GCS_BUCKET, ARTIFACT_REGISTRY_URL, CLOUD=gcp
    │   └── gpu-nodepool-gcp.yaml     ← T4 node selector + toleration patches
    ├── azure/
    │   ├── kustomization.yaml
    │   ├── configmap-azure.yaml      ← AZURE_BLOB_CONTAINER, ACR_URL, CLOUD=azure
    │   ├── gpu-nodepool-azure.yaml   ← V100 node selector + toleration patches
    │   └── keyvault-csi.yaml         ← Azure Key Vault CSI SecretProviderClass
    └── aws/
        ├── kustomization.yaml
        ├── configmap-aws.yaml        ← AWS_S3_BUCKET, ECR_URL, CLOUD=aws, AWS_REGION
        ├── gpu-nodepool-aws.yaml     ← g4dn T4 node selector + toleration patches
        ├── irsa-annotations.yaml     ← IAM Role annotation patches for service accounts
        └── storageclass-aws.yaml     ← gp3 StorageClass definition
```

---

## 10. Kubernetes Architecture

### 10.1 Deployment Standards

All services across all three environments follow the same deployment pattern:

| Setting | GCP (dev) | Azure (stage) | AWS (prod) |
|---|---|---|---|
| `replicas` minimum | 1 (save cost) | 2 (HA testing) | 2 (production HA) |
| `readinessProbe` | `/health/ready` | `/health/ready` | `/health/ready` |
| `livenessProbe` | `/health/live` | `/health/live` | `/health/live` |
| `resources.requests` | Required | Required | Required |
| `PodDisruptionBudget` | auth-service only | auth + model-router | auth + model-router |

### 10.2 StatefulSet StorageClass Per Cloud

| Service | GCP | Azure | AWS |
|---|---|---|---|
| PostgreSQL | `standard-rwo` (50GB) | `managed-premium` (50GB) | `gp3` (50GB, expandable) |
| Qdrant | `standard-rwo` (100GB dev subset) | `managed-premium` (200GB) | `gp3` (200GB, expandable) |
| Redis | `standard-rwo` (5GB) | `managed-premium` (10GB) | `gp3` (10GB) |
| RabbitMQ | `standard-rwo` (10GB) | `managed-premium` (20GB) | `gp3` (20GB) |

### 10.3 Ingress and TLS

All three environments use Nginx Ingress Controller. Cloudflare sits in front of all three — handling TLS termination, DDoS protection, and CDN. Cloudflare proxies traffic to the cloud load balancer for each environment:

| Environment | Subdomain | Cloud Load Balancer |
|---|---|---|
| Dev | `dev.maisys.x` / `api-dev.maisys.x` | GCP Cloud Load Balancer |
| Stage | `stage.maisys.x` / `api-stage.maisys.x` | Azure ALB |
| Production | `app.maisys.x` / `api.maisys.x` | AWS ALB |

### 10.4 Network Policy

Same network policy rules apply across all three clouds: module services can only reach their own database, their own Redis, RabbitMQ, Qdrant, and the shared services they need. External egress allowed for: Infermedica API, RxNorm API, SerpAPI, Drugs.com, HuggingFace Hub, LLM provider APIs.

---

## 11. CI/CD Pipeline — GitHub Actions

### 11.1 Full Branch and Environment Map

| Branch | Triggered By | Target | Cloud | Image Tag Pattern |
|---|---|---|---|---|
| `feature/*` | Push | Tests only — no deploy | None | None |
| `dev` | Push (after PR merge) | GCP dev | GCP GKE | `dev-{sha}` |
| `stage` | Manual PR: dev → stage | Azure staging | Azure AKS | `stage-{sha}` |
| `main` | Manual PR: stage → main | AWS production | AWS EKS | `release-{sha}` |
| `hotfix/*` | Push + hotfix label | AWS directly | AWS EKS | `hotfix-{sha}` |

### 11.2 Feature Branch Pipeline (Tests Only)

On push to any `feature/*` branch:
1. Python: `ruff check`, `black --check`, `isort --check`
2. TypeScript: `tsc --noEmit`, `eslint`
3. Unit tests (changed services only, path filtering)
4. Integration tests
5. Post results as PR status check

Target runtime: under 5 minutes. Failure blocks PR merge to `dev`.

### 11.3 Dev Branch Pipeline → GCP

On push to `dev` (after feature PR merged):
1. Full test suite for all changed services
2. Docker build for changed services only
3. Push to Google Artifact Registry: `us-central1-docker.pkg.dev/maisys-dev/{service}:dev-{sha}`
4. Update image tags in `k8s/overlays/gcp/kustomization.yaml`
5. `kubectl apply -k k8s/overlays/gcp/` (GKE context)
6. `kubectl rollout status deployment/{service}` for all changed services
7. Run smoke tests against `https://api-dev.maisys.x`
8. On failure: `kubectl rollout undo deployment/{service}` for all changed deployments

### 11.4 Stage Branch Pipeline → Azure

On merge of `dev` into `stage` (requires manual team approval + all GCP tests passing):
1. Full test suite (all services, not just changed)
2. Docker build for all services changed since last stage deploy
3. Push to Azure Container Registry: `maisys.azurecr.io/{service}:stage-{sha}`
4. Trigger database refresh job: restore latest AWS production backup to Azure staging DBs (async — monitored by separate job)
5. `kubectl apply -k k8s/overlays/azure/` (AKS context)
6. `kubectl rollout status` for all services
7. Run extended integration tests against `https://api-stage.maisys.x` (includes data-volume tests)
8. Notify Slack channel: "🟡 Stage deployed — {sha} — ready for validation"
9. On failure: auto-rollback + notify

**Azure auth in GitHub Actions:** Uses Azure Service Principal credentials stored as GitHub repository secrets (`AZURE_CREDENTIALS`). `az login --service-principal` → `az aks get-credentials`.

### 11.5 Main Branch Pipeline → AWS (Production)

On merge of `stage` into `main` (requires manual approval from 2 team members):
1. Full test suite — must pass at 100%
2. Docker build for all services changed since last production release
3. AWS ECR login: `aws ecr get-login-password | docker login --username AWS --password-stdin {ecr_url}`
4. Push to ECR: `{account}.dkr.ecr.us-east-1.amazonaws.com/maisys/{service}:release-{sha}`
5. `kubectl apply -k k8s/overlays/aws/` (EKS context)
6. `kubectl rollout status` with 5-minute timeout per service
7. Run production smoke tests against `https://api.maisys.x`
8. On success: create GitHub Release with release notes, tag commit as `v{version}`
9. Notify team: "🟢 Production deployed — release-{sha}"
10. On failure: immediate auto-rollback + PagerDuty alert

**AWS auth in GitHub Actions:** Uses GitHub Actions OIDC → AWS IAM Role federation. No long-lived AWS access keys stored in GitHub. The workflow assumes an IAM role via `aws-actions/configure-aws-credentials` with `role-to-assume`. Zero static credentials.

### 11.6 Hotfix Pipeline → AWS Direct

For urgent production fixes that cannot wait for the full dev → stage → main cycle:

1. Create `hotfix/fix-name` branch from `main`
2. Apply minimal fix, test locally
3. PR labeled `hotfix` — triggers abbreviated pipeline:
   - Tests only (no GCP deploy, no Azure deploy)
   - Docker build + push to ECR with `hotfix-{sha}` tag
   - Deploy directly to AWS production
   - Smoke tests
4. After hotfix is deployed and verified: back-merge to `stage` and `dev` to prevent divergence

### 11.7 Per-Service Image Building

GitHub Actions path filters determine which service images to rebuild on each push. Only services with changed files in their directory are rebuilt. Example: if only `services/drug-service/` changed, only the drug-service image is built and deployed. Unchanged services keep their running image. Target pipeline time: under 15 minutes for 1–3 changed services.

---

## 11. Monitoring and Observability

### 11.1 Monitoring Stack

| Tool | Purpose |
|---|---|
| Prometheus | Metrics collection from all services |
| Grafana | Dashboard visualization |
| Loki | Log aggregation (all service logs) |
| Promtail | Log shipping agent (sidecar on each pod) |
| Grafana Alerting | Alert rules and notification routing |

### 11.2 Metrics Exposed by All Services

Every FastAPI service exposes a `/metrics` endpoint in Prometheus format. The `shared/logger/middleware.py` automatically instruments all HTTP routes and WebSocket connections.

**Standard metrics from every service:**
- `http_requests_total{service, method, path, status_code}` — request counter
- `http_request_duration_seconds{service, method, path}` — latency histogram (P50/P95/P99)
- `http_requests_in_flight{service}` — concurrent requests gauge
- `websocket_connections_active{service}` — active WebSocket connections
- `websocket_messages_sent_total{service}` — total WebSocket messages

**LLM-specific metrics:**
- `llm_calls_total{service, provider, model, role}` — LLM call counter
- `llm_call_duration_seconds{service, provider, model}` — LLM latency histogram
- `llm_tokens_used_total{service, provider, model, type}` — token counter (input/output)
- `llm_errors_total{service, provider, model, error_type}` — LLM error counter

**Agent-specific metrics:**
- `agent_runs_total{service, agent_name, result}` — agent execution counter (success/error/timeout)
- `agent_duration_seconds{service, agent_name}` — agent execution time histogram
- `agent_tier2_triggered_total{service, feature}` — how often Tier 2 fallback activates
- `rag_chunks_retrieved{service, collection, tier}` — RAG retrieval results

**vLLM server metrics:**
- GPU utilization percentage
- GPU VRAM used / total
- Requests queued vs active
- Token generation throughput (tokens/second)

### 11.3 Grafana Dashboards

Five pre-built dashboards:

**Platform Overview:** All services request rates, error rates, P95 latency. Time range selector. Color-coded by service. Shows at a glance which services are under stress.

**AI Performance:** LLM call latency by provider, token usage per service per day, Tier 1 vs Tier 2 ratio per drug feature, vLLM GPU utilization and memory usage, chart LLM generation time.

**Symptom Checker:** Sessions started/completed/abandoned per day, average turns per session, triage level distribution (pie chart), emergency detections per day, Beta session count and review queue depth.

**Beta Training:** Dataset growth over time (total GP-approved records), GP review queue depth, training run history (accuracy trend), deployed model version history.

**Infrastructure:** Kubernetes pod health (running/pending/failed per service), node CPU/memory, PVC usage per StatefulSet, RabbitMQ queue depths, Redis memory usage per instance.

### 11.4 Alerting Rules

Critical alerts (page on-call immediately):
- Any service error rate > 5% for 5 consecutive minutes
- vLLM GPU OOM (GPU memory exhausted)
- Any service pod in CrashLoopBackoff for > 3 minutes
- RabbitMQ dead letter queue depth > 100 (messages failing repeatedly)
- PostgreSQL connection pool exhausted on any service
- Infermedica API error rate > 20% (symptom-service Alpha degraded)

Warning alerts (notify team, no immediate action required):
- P95 latency > 10 seconds on any service
- Tier 2 RAG fallback rate > 30% on drug-service (knowledge base coverage may need improvement)
- vLLM GPU utilization consistently > 90%
- Beta GP review queue depth > 200 (reviewers may need assistance)
- Token budget exceeded on more than 10% of agent runs in 1 hour

---

## 12. Logging Strategy

### 12.1 Structured Logging with structlog

All services use structlog for structured JSON logging. Every log entry is a JSON object — no free-text log messages. This makes logs searchable, filterable, and parseable by Loki without custom parsing rules.

Every log entry includes at minimum:
```json
{
  "timestamp": "2025-05-30T10:23:45.123Z",
  "level": "info",
  "service": "drug-service",
  "trace_id": "uuid",
  "session_id": "uuid",
  "user_id_hash": "sha256...",
  "event": "event_name",
  ...event-specific fields...
}
```

`user_id_hash` is a SHA-256 hash of the user ID — never the raw user ID in logs. This prevents PII exposure in log aggregation.

### 12.2 Key Events Logged Per Service

**All services:**
- Request received (method, path, user_id_hash, request_id)
- Request completed (status_code, duration_ms)
- Emergency keyword detected (session_id, keyword_category — never the keyword itself)
- LLM call started and completed (provider, model, tokens, duration_ms)
- Cache hit / miss (cache_key_hash, cache_type)
- RAG retrieval completed (collection, chunks_returned, tier, duration_ms)
- Agent started, node started/completed/error, agent completed (trace_id, duration_ms per node)

**drug-service additionally:**
- RxNorm normalization result (drug_name_hash, rxcui, canonical_name, fallback_used)
- Drug pair analysis (pair_hash, severity, source_tier)
- Drugs.com scraper triggered and result (pair_hash, duration_ms, success)

**symptom-service additionally:**
- Session started (interview_id, mode alpha/beta)
- Infermedica call completed (endpoint, duration_ms, response_summary)
- Session finalized (turns, triage_level, top_condition_name)
- Beta session anonymized and queued (session_id_hash)

**lab-service additionally:**
- File upload received (file_type, size_bytes, page_count)
- Processing path selected (path_a/b/c/d)
- Tests extracted (count, panel_names)
- Overall urgency determined (urgency_level)

### 12.3 Log Retention

- Hot storage (Loki, queryable): 30 days
- Cold storage (compressed archive in object storage): 1 year
- Agent trace logs (PostgreSQL `agent_trace_log` table): 30 days then purged

---

## 13. Rate Limiting and Timeouts

### 13.1 API Rate Limits

Applied at the API Gateway level for all external requests. Per-IP limits for unauthenticated requests. Per-user limits for authenticated requests (authenticated users get higher limits).

| Endpoint Category | Unauthenticated | Authenticated | Notes |
|---|---|---|---|
| Auth endpoints (login, register, OTP) | 5/min | 10/min | Brute force protection |
| Session start (any module) | Not allowed | 10/min | Must be logged in |
| Conversation turns (any module) | Not allowed | 30/min | |
| Drug features (all 12) | Not allowed | 20/min | |
| Lab report upload | Not allowed | 5/min | Heavy processing |
| Paper upload or discovery | Not allowed | 10/min | |
| Export generation | Not allowed | 5/min | Resource intensive |
| Admin endpoints | Not allowed | 60/min | Admin-only |

Rate limit exceeded → `429 Too Many Requests` with `Retry-After` header and a user-friendly message: "You've made too many requests. Please wait {N} seconds before trying again."

### 13.2 Timeout Matrix

All timeouts are configured as environment variables so they can be adjusted without code changes:

| Operation | Timeout | Service |
|---|---|---|
| External HTTP call (default) | 10s | All |
| RxNorm API | 5s | drug-service |
| Infermedica /parse | 10s | symptom-service |
| Infermedica /diagnosis | 15s | symptom-service |
| Infermedica /triage | 10s | symptom-service |
| Infermedica /conditions/{id} | 10s | symptom-service |
| Qdrant RAG search | 8s | all RAG-using services |
| Sufficiency evaluation LLM call | 10s | all RAG-using services |
| Drugs.com Playwright navigation | 20s | drug-service |
| Playwright element wait | 15s | drug-service |
| SerpAPI web search | 12s | drug-service, research-service |
| Semantic Scholar API | 15s | research-service |
| LLM generation (cloud) | 40s | all services |
| LLM generation (local vLLM) | 90s | all services |
| Agent graph total (most agents) | 90s | all services |
| Paper Discovery Agent total | 300s | research-service |
| OCR per page (PaddleOCR) | 30s | lab-service, research-service |
| OCR per page (Mistral/LightOn) | 20s | lab-service, research-service |
| Vision LLM per page | 30s | all vision-using services |
| Export generation | 30s | export-service |
| Translation service call | 8s | all services calling translation |

---

## 14. Scaling Strategy

### 14.1 Horizontal Pod Autoscaling (HPA)

HPA configured for all module services and the API gateway. Scales based on CPU utilization (70% trigger) and custom metrics (request queue depth, active WebSocket connections).

Minimum and maximum replicas:

| Service | Min Replicas | Max Replicas |
|---|---|---|
| api-gateway | 2 | 10 |
| chatbot-service | 2 | 8 |
| drug-service | 2 | 8 |
| symptom-service | 2 | 6 |
| lab-service | 1 | 6 |
| research-service | 1 | 6 |
| auth-service | 2 | 6 |
| translation-service | 1 | 4 |
| export-service | 1 | 4 |
| safety-service | 2 | 8 |

### 14.2 vLLM Scaling

The vLLM server scales vertically (larger GPU) before horizontally (multiple vLLM replicas). Running multiple vLLM replicas with the same model is possible but requires shared storage for model weights and a load balancer in front of the vLLM cluster. Start with one GPU node and scale to larger GPU type (T4 → A100) as concurrent LLM users increase. Add a second vLLM replica only when a single A100 is saturated.

### 14.3 Database Scaling

PostgreSQL is self-hosted in Kubernetes. Scale by adding a read replica (Patroni streaming replication) when read load is high. Module services can be configured to send read queries to the replica and write queries to the primary. This is added when analytics queries from the admin panel start affecting module service performance.

Qdrant scales by adding replica nodes to the Qdrant cluster. Medical RAG and Drug RAG collections can be replicated across nodes for read-heavy load. Paper RAG per-session collections are small and do not need replication.

---

## 15. Backup and Recovery

### 15.1 Backup Schedule

Backups run in the **AWS production environment** (authoritative source). AWS S3 is the primary backup destination. Azure staging is populated from AWS backups weekly. GCP dev databases are not backed up (dev data is disposable).

| Component | Method | Frequency | Retention | Storage |
|---|---|---|---|---|
| PostgreSQL (all production DBs) | `pg_dump` to AWS S3 | Daily at 02:00 UTC | 30 days | AWS S3 (`maisys-prod-backups`) |
| PostgreSQL (critical DBs: auth, symptom) | WAL archiving (continuous) | Continuous | 7 days | AWS S3 |
| Qdrant (Medical RAG + Drug RAG) | Qdrant snapshot API → S3 | Weekly | 4 snapshots | AWS S3 |
| Redis (all production instances) | RDB snapshot + AOF | RDB hourly, AOF continuous | 7 days | Local PVC + S3 |
| Model weights (LoRA adapters + merged) | S3 (immutable, versioned) | After each fine-tuning run | All versions forever | AWS S3 |
| Training datasets (JSONL files) | S3 (versioned bucket) | After each merge_and_split.py run | All versions forever | AWS S3 |
| Kubernetes manifests and configs | Git repository | Continuous (every commit) | Git history | GitHub |
| Azure staging databases | Restored from AWS S3 backup | Weekly (Monday 02:00 UTC) | 7 days of snapshots | Restored in-place |

### 15.2 AWS S3 Backup Bucket Policy

Production backups go to a dedicated S3 bucket (`maisys-prod-backups`) separate from the application storage bucket (`maisys-prod-storage`). Backup bucket configuration:
- Versioning: enabled (protects against accidental deletion)
- Server-side encryption: SSE-S3 (AES-256)
- Lifecycle policy: expire backups older than 30 days automatically
- Cross-region replication: optional (adds cost — evaluate after credits are exhausted)
- Access: only the backup IAM role can write; service accounts have read-only access

### 15.3 Azure Staging Database Refresh

Every Monday at 02:00 UTC, an automated job restores the latest AWS production backup to Azure staging databases. The job runs as a Kubernetes CronJob in the Azure cluster:

1. Download latest `pg_dump` file from AWS S3 (using cross-account IAM access or pre-signed URL)
2. Stop all Azure staging services (put them in maintenance mode)
3. Drop and recreate staging databases
4. Restore from downloaded backup using `pg_restore`
5. Run anonymization script: SHA-256 hash all `user_id` fields, remove email addresses, replace names with `user_{hash}` — ensures no real PII in staging
6. Restart staging services
7. Notify team: "Staging DB refreshed from production backup {date}"

This process takes approximately 15–30 minutes. It runs during low-traffic hours.

### 15.4 Recovery Procedures

**PostgreSQL production recovery (AWS):** Restore from S3 `pg_dump` backup using `pg_restore`. For point-in-time recovery (within 7-day WAL window), use `pg_basebackup` + WAL replay from S3. Test recovery quarterly by restoring to an isolated EKS namespace.

**Qdrant recovery:** Apply Qdrant snapshot via REST API. Medical and Drug RAG can be rebuilt from scratch by re-running the ingestion pipeline — this is slower (hours) but a valid fallback if the snapshot is corrupted. Per-session Paper RAG collections are ephemeral and do not need backup.

**Redis recovery:** Kubernetes restarts the Redis pod and loads from the RDB snapshot on the EBS PVC. Recent writes recovered from AOF log (up to 60 seconds of data may be lost).

**Model recovery:** All model versions stored in S3 with version metadata. Roll back by updating `active_model_config` in model-router-service PostgreSQL and reloading vLLM.

---

## 16. Security Architecture

### 16.1 Authentication and Authorization

**JWT tokens:** HS256 algorithm, 24-hour access token expiry, 7-day refresh token with rotation on use. Refresh token rotation: each use of a refresh token issues a new refresh token and invalidates the old one. Stolen refresh tokens cannot be reused after the legitimate user next authenticates.

**OTP:** 6-digit TOTP (Time-based One-Time Password) or HOTP delivered via email. 10-minute expiry. Single use — marked as consumed on verification. Bcrypt-hashed before storage.

**Google and Apple OAuth:** OAuth 2.0 flow. Access tokens from providers are never stored — only the user's profile information (email, name, provider user ID) is persisted. Provider access tokens are used once during the OAuth callback and discarded.

**Role-based access control:** Four roles (user, beta_user, gp_reviewer, admin). Every protected route in every service validates the JWT claim for the required role before processing. Role escalation requires admin action — users cannot self-elevate.

**Admin authentication:** Separate JWT issuer with a different secret key from user JWTs. Admin JWT claims contain an `admin: true` field that is verified separately. Admin IPs checked against a configured allowlist. MFA (TOTP authenticator app) required for all admin logins.

### 16.2 API Security

**CORS:** Configured on the API Gateway. Allowed origins: `https://app.maisys.x` and `https://admin.maisys.x` only. All other origins rejected with 403. No wildcard CORS.

**Input sanitization:** All user text inputs pass through `shared/security/input_sanitizer.py` before any processing. Strips: HTML tags, JavaScript event handlers, SQL injection patterns, path traversal sequences. Medical content (drug names, condition names) is preserved — only injection patterns are stripped.

**File security:** `shared/security/file_validator.py` validates all uploads with six layers: file extension whitelist, MIME type detection via python-magic, magic bytes validation (file signature), maximum size limit, maximum page count (PDFs), and basic malware pattern scan. Any failure rejects the file with a descriptive user-facing message.

**Request size limits:** API Gateway enforces maximum request body size: standard requests 1MB, file upload requests 50MB.

**Secrets:** No secrets in code, Docker images, or Git. All secrets in Kubernetes Secrets populated from cloud secret managers (GCP Secret Manager or Azure Key Vault). Secrets rotated quarterly.

**Dependencies:** `pip-audit` runs in CI on every commit. Any high-severity CVE in a Python dependency blocks the build.

### 16.3 Internal Network Security

All inter-service communication within the Kubernetes cluster is restricted by Kubernetes NetworkPolicies. Module services cannot reach each other's databases — only their own. NetworkPolicies whitelist the specific service pairs that are allowed to communicate. Unexpected inter-service traffic is blocked by default.

---

## 17. Data Privacy and User Data Handling

### 17.1 What MAISYS Collects

| Data | Stored | Purpose | Retention |
|---|---|---|---|
| Email address | Yes (hashed for lookup) | Auth, OTP, notifications | Account lifetime |
| Password | Yes (bcrypt, cost factor 12) | Auth | Account lifetime |
| Age and sex | Yes (per session) | Module functionality | Session + 90 days |
| Chief complaint / symptoms | Yes (per session) | Module functionality | 90 days |
| Lab report extracted values | Yes (per session) | Module functionality | 90 days |
| Chat messages | Yes | Session history | 90 days |
| Session results | Yes | History, export | 90 days |
| Beta sessions (consented) | Yes (anonymized) | Model training | Until consent withdrawn |
| IP addresses | Logs only | Rate limiting, security | 30 days |
| OAuth access tokens | Never stored | — | — |
| Health profile | Yes (user-entered, voluntary) | Personalized responses | Until user deletes |

### 17.2 User Rights

Users can at any time from their account settings:
- **Export all data:** Download a complete JSON export of all sessions, messages, and profile data
- **Delete account:** Permanently deletes account and all associated session data within 72 hours. Beta data (anonymized) is flagged for exclusion from the next training run.
- **Withdraw Beta consent:** Stops future Beta collection immediately. Existing anonymized data flagged for exclusion.
- **View data summary:** See a summary of what data MAISYS holds about them

### 17.3 Data Minimization

No data is collected beyond what is necessary for module functionality. Age and sex are stored per-session — not as permanent profile fields (unless user explicitly adds them to their voluntary health profile). Free-text symptom descriptions are not linked to identifiable profile fields in Beta storage — they are anonymized before any storage.

---

## 18. HIPAA-Aligned Practices

MAISYS is an educational health information platform — not a covered entity under HIPAA (it does not provide healthcare services, does not transmit health information for treatment or payment). However, MAISYS applies HIPAA-aligned technical safeguards as a baseline of responsible medical data handling.

| Safeguard | Implementation |
|---|---|
| Encryption at rest | PostgreSQL: TDE or pgcrypto for sensitive fields. Object storage: server-side encryption enabled (AES-256) on GCS and Azure Blob. |
| Encryption in transit | TLS 1.3 on all external connections (Cloudflare). Internal Kubernetes communication: TLS optional (can be enabled via service mesh if required). |
| Access controls | RBAC enforced at route level. Minimum privilege — services access only their own databases. |
| Audit logging | All admin actions logged with admin user ID, timestamp, and action details in `audit_log` table. |
| Automatic logoff | JWT 24-hour expiry. Frontend session timeout: 30 minutes of inactivity triggers re-authentication prompt. |
| Unique user identification | Each user has a UUID — no shared accounts. |

Organizations deploying MAISYS in a clinical context (e.g. as a pre-screening tool within a healthcare facility) must conduct their own HIPAA risk assessment and may need to execute Business Associate Agreements (BAAs) with cloud providers.

---

## 19. Beta Data Compliance

### 19.1 Consent Requirements

All three gates must be recorded with timestamps before any Beta endpoint responds. The middleware checks gate completion on every Beta API request:
- Gate 1: Explicit consent screen — user clicks "I Understand & I Consent"
- Gate 2: Account settings Beta participation toggle — explicitly set to ON by user
- Gate 3: Onboarding flow 3-step completion — user completes all 3 steps

### 19.2 Anonymization Standards

Applied as a code function before any Beta session data is stored anywhere (including the review queue):
- User ID replaced with SHA-256 hash (one-way)
- PII removed using regex patterns (phone numbers, email addresses) and scispaCy NER (distinguishes person names from drug names)
- Session date shifted by a random ±30 days per session
- Geographic identifiers below city level removed

GP reviewers access only anonymized records. They cannot identify the originating user.

### 19.3 Consent Withdrawal

On withdrawal: Beta access revoked immediately (403 on all Beta endpoints), no new sessions collected, existing records in `beta_review_queue` and any training datasets flagged with `withdrawn: true` — excluded from all future training runs. Withdrawal timestamp recorded.

---

## 20. Master Implementation Checklist

This checklist defines every task required to build, test, and deploy the complete MAISYS platform. Tasks are ordered by dependency — earlier tasks must complete before later tasks can begin. Work through this list sequentially.

### Phase 1 — Foundation (Week 1–2)

**Monorepo Setup:**
- [ ] Initialize Git repository with `dev` and `main` branches
- [ ] Create monorepo folder structure: `services/`, `shared/`, `frontend/`, `data-pipeline/`, `k8s/`, `monitoring/`
- [ ] Set up `.github/workflows/` with feature branch test pipeline

**Shared Library:**
- [ ] `shared/error_handler/` — base exception hierarchy, global handler, standardized APIResponse
- [ ] `shared/logger/` — structlog setup, request logging middleware
- [ ] `shared/auth/` — JWT decode/validate, FastAPI Depends() for protected routes
- [ ] `shared/models/` — SQLAlchemy declarative base, pagination schemas
- [ ] `shared/security/` — file_validator, filename_sanitizer, input_sanitizer
- [ ] `shared/rate_limiter/` — slowapi setup, LLM semaphore limiter

**Infrastructure Services:**
- [ ] auth-service: all tables, all endpoints, JWT + refresh token + OTP + Google + Apple OAuth
- [ ] notification-service: email delivery with SendGrid + SMTP fallback
- [ ] model-router-service: model registry tables, active config table, all endpoints, admin switch endpoint
- [ ] safety-service: emergency detection (AR + EN), disclaimer injection, profile-aware warnings
- [ ] translation-service: Google Translate + deep-translator fallback + LLM mode + Redis cache

**Local Development:**
- [ ] `docker-compose.yml` with all services, per-service PostgreSQL, per-service Redis, Qdrant, RabbitMQ, vLLM
- [ ] All service Dockerfiles
- [ ] Verify `docker-compose up --build` starts all services without error

### Phase 2 — Data Collection (Week 2–4, runs in parallel with Phase 3)

**Drugs.com:**
- [ ] Verify `drugs_general_scraper.py` complete output: 17,432 PDFs in `drugs_general_output/`
- [ ] Continue `scraper_professional.py` until complete
- [ ] Run `retry_failed_drugs.py` after professional scraper finishes

**MedlinePlus:**
- [ ] Run `part1_health_topics/scraper.py` → verify `health_topics.json`
- [ ] Run `part2_drugs/scraper.py` → verify `drugs.json` + `brand_mappings.json`
- [ ] Run `part3_lab_tests/scraper.py` → verify `lab_tests.json`
- [ ] Run `part4_encyclopedia/scraper.py` → verify `encyclopedia.json`
- [ ] Run `part5_genetics/scraper.py` → verify `genetics.json`

**Mayo Clinic:**
- [ ] Run `part1_diseases_conditions/scraper.py` → verify `diseases_conditions.json`
- [ ] Run `part2_symptoms/scraper.py` → verify `symptoms.json`
- [ ] Run `part3_tests_procedures/scraper.py` → verify `tests_procedures.json`
- [ ] Run `part4_drugs/scraper.py` → verify `drugs_supplements.json`

**Verification after all scrapers:**
- [ ] All JSON output files present and non-empty
- [ ] Success rate > 95% on all scrapers
- [ ] Sample 10 records from each output file and verify schema compliance

### Phase 3 — Shared Infrastructure (Week 3–5)

**Shared Library — Advanced:**
- [ ] `shared/llm_client/` — LiteLLM wrapper, retry, timeout, circuit breaker, KV cache manager, prefix cache formatter
- [ ] `shared/chunking/` — medical chunker, section detector, token counter
- [ ] `shared/embedding/` — MiniLM embedder, PubMedBERT embedder, dual embedder, similarity
- [ ] `shared/concurrent/` — gather_with_limit, batch_processor, progress_tracker
- [ ] `shared/progress/` — Redis pub/sub publisher, standard event types
- [ ] `shared/storage/` — storage client interface, GCS backend, Azure Blob backend

**RAG Ingestion:**
- [ ] Drug RAG ingestion pipeline: Drug service — `run_drug_ingestion.py` (all 4 sources)
- [ ] Verify Qdrant `drug_minilm` and `drug_pubmedbert` collections populated
- [ ] Medical RAG ingestion pipeline: chatbot service — `run_all_ingestion.py` (all 7 sources)
- [ ] Verify Qdrant `medical_minilm` and `medical_pubmedbert` collections populated
- [ ] Test queries: 5 drug queries returning correct chunks from Drug RAG
- [ ] Test queries: 5 medical topic queries returning correct chunks from Medical RAG
- [ ] Test queries: 5 lab test queries returning correct chunks from Medical RAG

**RxNorm:**
- [ ] `rxnorm_client.py` implemented and tested
- [ ] "Tylenol" → acetaminophen, RxCUI: 161 ✓
- [ ] "Percocet" → oxycodone + acetaminophen (combination drug decomposition) ✓
- [ ] RxNorm API down → Redis cache fallback ✓

### Phase 4 — Module Services (Week 4–8)

**chatbot-service:**
- [ ] All routes, services, repository layers
- [ ] Three-LLM architecture: medical LLM + enhancement layer + chart LLM
- [ ] Sliding window conversation memory (10 messages + rolling summary)
- [ ] Vision model pipeline (image + scanned PDF detection)
- [ ] File upload to session Qdrant namespace
- [ ] STT + TTS (all providers, selector pattern)
- [ ] KV cache (local past_key_values + cloud prefix caching)
- [ ] Visual agents: Chart + Infographic + Diagram
- [ ] Visual orchestrator: auto-trigger detection rules
- [ ] Playwright renderer: HTML → PNG
- [ ] Share URL generation and read-only access
- [ ] Health profile injection
- [ ] WebSocket progress events (all 16 pipeline steps)
- [ ] Live agent activity events (all event types)
- [ ] Test: full conversation, vision input, file upload, visual generation, export

**drug-service:**
- [ ] LangGraph migration from all old patterns
- [ ] RxNorm normalization service (pure code)
- [ ] Drug pair generator (pure code)
- [ ] Two-tier retrieval router + sufficiency evaluator
- [ ] All 6 drug agents: Lookup, Interaction, Dosage, Comparison, Pharmacokinetics, Alternative
- [ ] Web Search Agent (Drugs.com Playwright flow — exact 10-step implementation)
- [ ] Drug Acquisition Agent (async background pipeline)
- [ ] All 12 features tested end-to-end
- [ ] Drug-drug interaction with Tier 2 fallback tested
- [ ] Concurrent pair analysis tested (6 pairs from 4 drugs)
- [ ] Visual auto-triggers tested per feature

**symptom-service:**
- [ ] Alpha mode: complete 18-step pipeline
- [ ] Infermedica client: all 5 endpoints with Dev-Mode: false in production
- [ ] All 4 LLM tasks: rephrase, parse, explain, triage summary
- [ ] All 4 stop conditions (code implementation)
- [ ] Emergency interrupt via LangGraph interrupt()
- [ ] Medical RAG enrichment (concurrent with condition detail calls)
- [ ] Triple consent gates (middleware enforcement)
- [ ] Beta mode: fine-tuned LLM via vLLM
- [ ] Beta anonymization pipeline (before storage)
- [ ] GP review queue events (RabbitMQ publish)
- [ ] Test: complete Alpha 8-turn session, finalization, export

**lab-service:**
- [ ] File routing (4 paths: digital PDF / scanned PDF / image / DOCX)
- [ ] Vision LLM for image and scanned PDF paths
- [ ] DOCX processing (python-docx tables + paragraphs)
- [ ] Stage 1 rule-based parser (regex + scispaCy)
- [ ] Stage 2 LLM structured validator
- [ ] Concurrent explanation generation (asyncio.gather, semaphore 5)
- [ ] Per-test streaming explanations
- [ ] Overall summary with urgency level
- [ ] Chart Agent auto-trigger (bar chart of values vs ranges)
- [ ] Infographic Agent auto-trigger (abnormal test cards)
- [ ] Follow-up chat workspace (same pipeline as chatbot)
- [ ] Test: digital PDF, scanned PDF, image, DOCX — all paths verified

**research-service:**
- [ ] Paper ingestion pipeline (8 steps)
- [ ] Paper Discovery Agent (5-node LangGraph graph)
- [ ] Paper download attempt + pending upload fallback
- [ ] Pending upload UI slot and re-upload handling
- [ ] Paper RAG per-session collections (creation, search, deletion)
- [ ] Paper chat with full chatbot feature parity (KV cache, STT/TTS, vision, memory, visual agents, health profile, share URL)
- [ ] Summarization: model mode (DistilBART) + LLM mode
- [ ] Translation: model mode (opus-mt) + LLM mode
- [ ] Q&A generation: model mode (T5) + LLM mode
- [ ] Comparison: always LLM mode, concurrent RAG across papers
- [ ] Share URL for research sessions
- [ ] Test: upload paper, chat about it, run all 4 NLP tools, comparison

### Phase 5 — Admin and Export (Week 6–8)

**admin-service:**
- [ ] Admin auth (separate JWT issuer, IP allowlist, MFA)
- [ ] GP review dashboard: queue list, review actions, correction form
- [ ] User management: list, role change, Beta revoke
- [ ] System monitoring: metrics aggregation from model-router-service
- [ ] Model performance tracker: training runs display, deploy button

**export-service:**
- [ ] RabbitMQ consumer for `export.request` queue
- [ ] TXT generator (all modules)
- [ ] DOCX generator with Arabic RTL (all modules)
- [ ] PDF generator with Noto Sans Arabic (all modules)
- [ ] Visual PNG embedding in DOCX and PDF
- [ ] Test: export from each of the 5 module services in all 3 formats, Arabic and English

### Phase 6 — Frontend (Week 7–10)

- [ ] Project setup: React + TypeScript + Vite + Tailwind + Redux Toolkit
- [ ] i18n setup: react-i18next with Arabic and English translation files
- [ ] RTL layout: useRTL hook, Tailwind directional utilities
- [ ] Light/Dark mode: useTheme hook, Tailwind dark: prefix
- [ ] WebSocket hook: useWebSocket — connection management, reconnection, event dispatch
- [ ] Voice hook: useVoice — STT recording, TTS playback
- [ ] Axios HTTP client with auth interceptors (JWT attach + refresh on 401)
- [ ] All 29 pages implemented (28 user-facing + 1 admin login)
- [ ] Agent Activity live panel component
- [ ] Visual iframe component (receives HTML from WebSocket, renders in sandbox)
- [ ] Progress bar component (smooth animation, ETA display)
- [ ] Streaming text component (append-on-token behavior)
- [ ] Citation component
- [ ] Lab test result card component
- [ ] Drug comparison table component
- [ ] Symptom checker conversation component
- [ ] Test: full user journey for each of the 5 modules in both Arabic and English

### Phase 7 — Deployment (Week 9–12)

**GCP — Development Environment:**
- [ ] GKE cluster created (us-central1, CPU node pool + GPU preemptible node pool)
- [ ] All Kubernetes base manifests written (`k8s/base/`)
- [ ] GCP Kustomize overlay configured (`k8s/overlays/gcp/`)
- [ ] GitHub Actions `dev→GCP` pipeline working (`deploy-gcp.yml`)
- [ ] Dev databases initialized (per-service PostgreSQL StatefulSets)
- [ ] Dev Qdrant initialized with representative knowledge base subset
- [ ] vLLM running on GPU node with Meditron-7B (dev)
- [ ] Infermedica API reachable from GCP pods
- [ ] All 6 load test scenarios run and results recorded
- [ ] Load test results meet all targets

**Azure — Staging Environment:**
- [ ] AKS cluster created (eastus)
- [ ] Azure Blob Storage + Key Vault configured
- [ ] Azure Kustomize overlay configured (`k8s/overlays/azure/`)
- [ ] GitHub Actions `stage→Azure` pipeline working (`deploy-azure.yml`)
- [ ] Full knowledge base ingested (all Medical RAG + full Drug RAG + DDIMDL)
- [ ] Production database snapshot restored from AWS (first population)
- [ ] Database refresh job configured (weekly restore from AWS S3 backup)
- [ ] vLLM running with production models
- [ ] Extended integration tests passing against production-scale data
- [ ] Staging subdomain active: `stage.maisys.x` and `api-stage.maisys.x`
- [ ] Azure Monitor alerting configured for staging

**AWS — Production Environment ($100 credits):**
- [ ] EKS cluster created (us-east-1, t3.medium CPU nodes + g4dn.xlarge Spot GPU)
- [ ] AWS ECR repositories created for all 14 services
- [ ] S3 bucket created for production storage (model weights, exports, backups)
- [ ] AWS IAM roles and IRSA configured for all service accounts
- [ ] AWS Secrets Manager or SSM Parameter Store populated with production secrets
- [ ] AWS Kustomize overlay configured (`k8s/overlays/aws/`)
- [ ] gp3 StorageClass defined for StatefulSet PVCs
- [ ] GitHub Actions `main→AWS` pipeline working (`deploy-aws.yml`) with OIDC auth
- [ ] Production knowledge base ingested (full corpus — identical to staging)
- [ ] Production databases initialized and verified
- [ ] Production vLLM running with full model set
- [ ] Hotfix pipeline (`hotfix/*→AWS`) tested
- [ ] AWS CloudWatch alerts configured (mirrors GCP/Azure alert rules)
- [ ] First production smoke tests passing
- [ ] AWS cost monitoring enabled — set billing alert at $80 (before $100 credit exhausts)

**Domain and DNS:**
- [ ] Domain purchased (maisys.org or maisys.cloud) managed via Cloudflare
- [ ] Subdomains configured in Cloudflare DNS:
  - `app.maisys.x` → AWS ALB (production)
  - `api.maisys.x` → AWS ALB (production)
  - `admin.maisys.x` → AWS ALB (production)
  - `stage.maisys.x` → Azure ALB (staging)
  - `api-stage.maisys.x` → Azure ALB (staging)
  - `dev.maisys.x` → GCP Load Balancer (development)
  - `api-dev.maisys.x` → GCP Load Balancer (development)
- [ ] Wildcard SSL certificate active via Cloudflare
- [ ] HTTP → HTTPS redirect active on all subdomains

### Phase 8 — Beta Training (Week 10+, ongoing)

- [ ] Infermedica scraper run (full — all ~1,100 seed symptoms)
- [ ] EndlessMedical scraper run
- [ ] `infermedica_to_beta_training.py` run → 8 JSONL files generated
- [ ] `download_medical_datasets.py` run → HuggingFace datasets downloaded
- [ ] All 6 manual dataset downloads completed (MTSamples, MIMIC-III, PrimeKG, MIT KG, Mendeley, Kaggle)
- [ ] All 5 normalizers run → normalized JSONL files generated
- [ ] `merge_and_split.py` run → combined_train/val/test.jsonl generated
- [ ] `quality_checker.py` run → all quality gates passed
- [ ] First fine-tuning run: `finetune_lora.py` with Meditron-7B
- [ ] `evaluate_model.py` run → triage accuracy ≥ 85%, emergency false negative = 0%
- [ ] `push_to_vllm.py` → Beta model deployed to vLLM
- [ ] Beta endpoint tested with triple-consented test account
- [ ] Beta GP review dashboard functional for GP reviewers

### Phase 9 — Monitoring and Operations (Week 11–12)

- [ ] Prometheus scraping all service `/metrics` endpoints
- [ ] All 5 Grafana dashboards configured
- [ ] All alerting rules active and tested (trigger test alerts manually)
- [ ] Loki log aggregation: all pods shipping logs via Promtail sidecar
- [ ] Log search: Loki queries working for trace_id, session_id, service
- [ ] Agent trace logs: PostgreSQL `agent_trace_log` table populated by live requests
- [ ] Admin panel model tracker: showing training runs + deployed version
- [ ] Backup schedule active: PostgreSQL daily backup to object storage
- [ ] Qdrant weekly snapshot configured
- [ ] Redis RDB + AOF configured on all instances
- [ ] Recovery test: restore PostgreSQL from backup in test namespace

---

*MAISYS Technical Development Guide — Part 4: Beta Training Pipeline · Frontend · Deployment · Operations · Security · Master Checklist*

*End of Part 4 — End of MAISYS Technical Development Guide*
