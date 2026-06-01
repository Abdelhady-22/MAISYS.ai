# MAISYS — Technical Development Guide
## Part 2: Data Collection · Extraction · Chunking · RAG Knowledge Base

---

## Table of Contents

1. [Data Sources Overview](#1-data-sources-overview)
2. [Drugs.com Scrapers](#2-drugscom-scrapers)
3. [MedlinePlus Scrapers — 5 Parts](#3-medlineplus-scrapers--5-parts)
4. [Mayo Clinic Scrapers — 4 Parts](#4-mayo-clinic-scrapers--4-parts)
5. [Infermedica API Scraper](#5-infermedica-api-scraper)
6. [EndlessMedical API Scraper](#6-endlessmedical-api-scraper)
7. [Text and Table Extraction — Per Source](#7-text-and-table-extraction--per-source)
8. [Chunking Strategies — Per Source](#8-chunking-strategies--per-source)
9. [Three RAG Systems](#9-three-rag-systems)
10. [Qdrant Collections — Full Schema](#10-qdrant-collections--full-schema)
11. [Dual Embedding Pipeline](#11-dual-embedding-pipeline)
12. [Ingestion Pipelines — Per Module](#12-ingestion-pipelines--per-module)
13. [Sufficiency Evaluation](#13-sufficiency-evaluation)
14. [Two-Tier Retrieval Pattern](#14-two-tier-retrieval-pattern)
15. [Scraping and Ingestion Run Order](#15-scraping-and-ingestion-run-order)

---

## 1. Data Sources Overview

### 1.1 Complete Source Map

| Source | Scraper | Output Format | RAG System | Used By | Status |
|---|---|---|---|---|---|
| Drugs.com general | `drugs_general_scraper.py` | PDFs (17,432 drugs) | Drug RAG | drug-service, chatbot | ✅ Complete |
| Drugs.com professional | `scraper_professional.py` | PDFs (6,450+ drugs) | Drug RAG | drug-service, chatbot | 🔄 In progress |
| Drugs.com failed retry | `retry_failed_drugs.py` | PDFs (42 failed URLs) | Drug RAG | drug-service, chatbot | ⏳ Pending |
| MedlinePlus health topics | `part1_health_topics/scraper.py` | `health_topics.json` | Medical RAG | chatbot | ⏳ Pending |
| MedlinePlus drugs | `part2_drugs/scraper.py` | `drugs.json` | Drug RAG | drug-service, chatbot | ⏳ Pending |
| MedlinePlus lab tests | `part3_lab_tests/scraper.py` | `lab_tests.json` | Medical RAG | lab-service, chatbot | ⏳ Pending |
| MedlinePlus encyclopedia | `part4_encyclopedia/scraper.py` | `encyclopedia.json` | Medical RAG | chatbot | ⏳ Pending |
| MedlinePlus genetics | `part5_genetics/scraper.py` | `genetics.json` | Medical RAG | chatbot | ⏳ Pending |
| Mayo Clinic diseases | `part1_diseases_conditions/scraper.py` | `diseases_conditions.json` | Medical RAG | chatbot, symptom | ⏳ Pending |
| Mayo Clinic symptoms | `part2_symptoms/scraper.py` | `symptoms.json` | Medical RAG | chatbot, symptom | ⏳ Pending |
| Mayo Clinic tests | `part3_tests_procedures/scraper.py` | `tests_procedures.json` | Medical RAG | lab-service, chatbot | ⏳ Pending |
| Mayo Clinic drugs | `part4_drugs/scraper.py` | `drugs_supplements.json` | Drug RAG | drug-service, chatbot | ⏳ Pending |
| Infermedica API | `infermedica_scraper.py` | `diagnosis_flows.json` + others | Beta training only | symptom-service Beta | ⏳ Pending |
| EndlessMedical API | `endlessmedical_scraper.py` | `feature_sessions.json` + others | Beta training only | symptom-service Beta | ⏳ Pending |
| Research papers | Uploaded by user or downloaded by agent | Per-session Qdrant collection | Paper RAG | research-service | On demand |
| DDIMDL Interactions (DrugBank 5.1.3) | `ingest_ddimdl.py` (manual CSV — no scraper needed) | 37,264 interaction records | Drug RAG + PostgreSQL lookup | drug-service | ✅ Files in hand |
| DDIMDL Drug Features (DrugBank 5.1.3) | `ingest_ddimdl.py` | 572 molecular drug profiles | PostgreSQL molecular table | drug-service | ✅ Files in hand |

### 1.2 Which RAG Feeds Which Service

**Medical RAG** (consumed by chatbot-service, lab-service, symptom-service):
- MedlinePlus health topics
- MedlinePlus lab tests
- MedlinePlus encyclopedia
- MedlinePlus genetics
- Mayo Clinic diseases and conditions
- Mayo Clinic symptoms
- Mayo Clinic tests and procedures

**Drug RAG** (consumed by drug-service as primary; chatbot-service for drug questions):
- Drugs.com general PDFs (17,432 drugs — patient-facing)
- Drugs.com professional PDFs (6,450+ drugs — clinical/prescribing)
- MedlinePlus drugs
- Mayo Clinic drugs and supplements
- DDIMDL Interactions — 37,264 natural-language drug-drug interaction descriptions from DrugBank 5.1.3 (Deng et al., Bioinformatics, 2020)

**Paper RAG** (consumed by research-service only — per session):
- User-uploaded PDFs and DOCX files
- Papers downloaded by the Paper Discovery Agent

### 1.3 Infermedica and EndlessMedical Data

These two sources feed the Beta training pipeline only. They are not ingested into any RAG system.

- `diagnosis_flows.json` (Infermedica) → `infermedica_to_beta_training.py` → 8 JSONL training formats
- `feature_sessions.json` + `multi_feature_sessions.json` (EndlessMedical) → same converter
- Output: `beta_training/combined_train.jsonl`, `combined_val.jsonl`, `combined_test.jsonl`

---

## 2. Drugs.com Scrapers

### 2.1 General Scraper (`drugs_general_scraper.py`)

**Target:** Consumer-facing drug pages on Drugs.com — patient information, uses, side effects, warnings, dosage, interactions in plain language.

**URL pattern:** `https://www.drugs.com/{drugname}.html`

**Index navigation:** Uses alphabetical combination patterns (`/alpha/a.html`, `/alpha/aa.html`, `/alpha/ab.html` ... through all letter combinations) to discover all drug URLs. All URLs collected before scraping begins.

**Output:** One PDF per drug saved to `drugs_general_output/` with organized folder structure: `drugs_general_output/{first_letter}/{two_letter_prefix}/{drugname}.pdf`

Example: acetaminophen → `drugs_general_output/a/ac/acetaminophen.pdf`

**Status:** Complete — 17,432 drugs successfully scraped (99.76% success rate). Results recorded in `results_general_final_20260201_081050.json`.

**Resume behavior:** The scraper saves progress every 50 drugs. If interrupted, it resumes from the last checkpoint by reading existing results and skipping already-scraped URLs.

**PDF settings:** A4 format, print background enabled, 15mm top/bottom margins, 10mm left/right margins.

**Rate limiting:** 2-second delay between requests. Headless Chromium via Playwright.

### 2.2 Professional Scraper (`scraper_professional.py`)

**Target:** Professional/clinical drug pages — package inserts, prescribing information, mechanism of action, pharmacokinetics, full clinical documentation.

**URL pattern:** `https://www.drugs.com/pro/{drugname}` (note: no .html extension)

**How URLs are derived:** The scraper first collects consumer URLs from the alphabetical listing with `?pro=1` parameter, then converts each to the `/pro/` equivalent. Example: `https://www.drugs.com/acetaminophen.html` → `https://www.drugs.com/pro/acetaminophen`

**Output:** One PDF per drug saved to `drugs_professional_output/` with the same organized folder structure as the general scraper, but PDFs are named with `_pro` suffix to distinguish them.

Example: `drugs_professional_output/a/ac/acetaminophen_pro.pdf`

**Status:** In progress — 6,450+ drugs scraped at last checkpoint (`progress_professional_6450_20260330_070719.json`). Continue running until complete.

**Resume behavior:** Same checkpoint pattern as general scraper — reads existing progress JSON, skips already-scraped URLs.

### 2.3 Failed Drugs Retry Script (`retry_failed_drugs.py`)

**Purpose:** Recover the 42 drugs that failed during the general scraping run.

**Input:** Read `results_general_final_20260201_081050.json`, filter records where `status != "success"` — these are the 42 failed URLs.

**Retry sequence per URL:**
- Attempt 1: Same URL with a different User-Agent string (rotate through 5 different browser UA strings)
- Attempt 2: Same URL with a longer random delay (15–30 seconds between attempts)
- Attempt 3: Fresh Playwright browser context (new browser instance, no session state from previous attempts)
- Attempt 4: Try the `/pro/` URL variant — some drugs that redirect on the consumer path work on the professional path

**Output:** Same PDF format and folder structure as the original general scraper. Successful retries added to `drugs_general_output/`. Final report saved as `retry_results_{timestamp}.json` listing which URLs were recovered, which failed all 4 attempts, and which attempt succeeded for each.

**Remaining failures:** Any URL that fails all 4 attempts is logged with its error reason. These are flagged for manual review and added to a `manual_review_list.txt`. The Drug Data Acquisition Agent handles these on demand when a user queries a drug that has no RAG data.

---

## 3. MedlinePlus Scrapers — 5 Parts

All MedlinePlus scrapers use the shared `utils.py` which provides: HTTP session with retry logic (3 attempts, exponential backoff), random delay between requests (3–8 seconds), content cleaning (removes nav, footer, sidebar, disclaimer boilerplate), section extraction (h2/h3 heading → content mapping), atomic JSON write (writes to .tmp then renames to prevent corruption on crash), and resume/checkpoint loading.

### 3.1 Part 1 — Health Topics

**Script:** `medlineplus/part1_health_topics/scraper.py`

**Index URL:** `https://medlineplus.gov/all_healthtopics.html`

**What it scrapes:** All health topic pages listed in the single alphabetical listing (~1,060 topics). Handles both direct topic entries and "alias see canonical" redirect entries — aliases are recorded as `also_known_as` on the canonical topic record.

**URL filter:** Only root-level `.html` pages on medlineplus.gov are accepted. Skips: `/druginfo/`, `/ency/`, `/genetics/`, `/lab-tests/`, `/about/`, `/spanish/`, navigation links, and any link not pointing to a real health topic page.

**Per-page extraction:** Fetches each topic page, strips navigation and sidebar boilerplate, extracts h1 as topic name, extracts `#topic-summary` div as the topic summary prose, then extracts all h2/h3 heading + content pairs as sections.

**Output:** `medlineplus_scraper/part1_health_topics/output/health_topics.json`

**Output schema per record:**
```
{
  "type": "health_topic",
  "name": "Headache",
  "url": "https://medlineplus.gov/headache.html",
  "also_known_as": ["Head pain", "Cephalalgia"],
  "summary": "A headache is pain or discomfort in the head...",
  "sections": [
    {"heading": "Start Here", "content": "..."},
    {"heading": "Diagnosis and Tests", "content": "..."},
    {"heading": "Treatments and Therapies", "content": "..."}
  ],
  "status": "success",
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (chatbot-service)

### 3.2 Part 2 — Drugs and Supplements

**Script:** `medlineplus/part2_drugs/scraper.py`

**Index pattern:** One page per letter: `https://medlineplus.gov/druginfo/drug_{Letter}a.html` for A–Z, plus `drug_00.html` for digit entries (27 index pages total).

**What it scrapes:** All individual drug monograph pages. Captures both direct drug entries and brand→generic redirect entries. Brand/generic mappings saved separately for use by the drug normalization pipeline.

**URL filter:** Only `/druginfo/meds/` or `/druginfo/natural/` paths are accepted as real drug pages.

**Per-page extraction:** Strips nav/footer, extracts drug name from h1, extracts brand names from any brand-name div, extracts all sections (typical sections: What Is, Why, How, Side Effects, Precautions, Storage, Overdose).

**Output files:**
- `medlineplus_scraper/part2_drugs/output/drugs.json` — all drug records
- `medlineplus_scraper/part2_drugs/output/brand_mappings.json` — brand→generic mappings

**Output schema per record:**
```
{
  "type": "drug",
  "name": "Ibuprofen",
  "url": "https://medlineplus.gov/druginfo/meds/a682159.html",
  "brand_names": ["Advil", "Motrin", "Nuprin"],
  "sections": [
    {"heading": "Why is this medication prescribed?", "content": "..."},
    {"heading": "How should this medicine be used?", "content": "..."},
    {"heading": "What side effects can this medication cause?", "content": "..."},
    {"heading": "What precautions should I follow?", "content": "..."},
    {"heading": "What should I do if I forget a dose?", "content": "..."},
    {"heading": "How should this medicine be stored?", "content": "..."}
  ],
  "status": "success",
  "scraped_at": "2025-..."
}
```

**Feeds:** Drug RAG (drug-service, chatbot-service)

### 3.3 Part 3 — Lab Tests

**Script:** `medlineplus/part3_lab_tests/scraper.py`

**Index URL:** `https://medlineplus.gov/lab-tests/`

**What it scrapes:** All individual lab test pages listed on the lab tests index. The index is a single page with all tests listed alphabetically.

**URL filter:** Must contain `/lab-tests/` in the path with a non-empty slug after it. Index page itself is excluded.

**Per-page extraction:** Strips nav/footer, extracts test name from h1, extracts all sections.

**Typical sections per lab test page:** What is a [test name] test?, Why do I need it?, What happens during the test?, What do the results mean?, Is there anything else I need to know?

**Output:** `medlineplus_scraper/part3_lab_tests/output/lab_tests.json`

**Output schema per record:**
```
{
  "type": "lab_test",
  "name": "Complete Blood Count (CBC)",
  "url": "https://medlineplus.gov/lab-tests/complete-blood-count/",
  "sections": [
    {"heading": "What is a complete blood count (CBC)?", "content": "..."},
    {"heading": "What is it used for?", "content": "..."},
    {"heading": "Why do I need a CBC?", "content": "..."},
    {"heading": "What do the results mean?", "content": "..."},
    {"heading": "Normal range", "content": "..."}
  ],
  "status": "success",
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (lab-service, chatbot-service)

### 3.4 Part 4 — Medical Encyclopedia

**Script:** `medlineplus/part4_encyclopedia/scraper.py`

**Index pattern:** 27 pages — `https://medlineplus.gov/ency/encyclopedia_{Letter}.htm` for A–Z, plus `encyclopedia_0-9.htm`.

**What it scrapes:** All encyclopedia articles. Encyclopedia articles have 6-digit numeric IDs in their URLs (e.g. `/ency/article/003888.htm`). The scraper identifies articles by this pattern.

**Per-page extraction:** Strips nav/footer, extracts article title from h1, extracts all h2/h3 sections. Encyclopedia articles cover specific medical procedures, conditions, anatomy, and medical concepts in more clinical detail than health topics.

**Output:** `medlineplus_scraper/part4_encyclopedia/output/encyclopedia.json`

**Output schema per record:**
```
{
  "type": "encyclopedia",
  "name": "Liver biopsy",
  "url": "https://medlineplus.gov/ency/article/003895.htm",
  "sections": [
    {"heading": "Definition", "content": "..."},
    {"heading": "How the Test is Performed", "content": "..."},
    {"heading": "How to Prepare for the Test", "content": "..."},
    {"heading": "Normal Results", "content": "..."},
    {"heading": "What Abnormal Results Mean", "content": "..."},
    {"heading": "Risks", "content": "..."}
  ],
  "status": "success",
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (chatbot-service)

### 3.5 Part 5 — Genetics

**Script:** `medlineplus/part5_genetics/scraper.py`

**Index URLs (two):**
- `https://medlineplus.gov/genetics/condition/` — all genetic conditions
- `https://medlineplus.gov/genetics/gene/` — all gene pages

**What it scrapes:** Individual condition pages (e.g. cystic fibrosis, sickle cell disease) and gene pages (e.g. BRCA1, TP53). Each has a distinct URL pattern: `/genetics/condition/{slug}/` or `/genetics/gene/{slug}/`.

**Per-page extraction:** Strips nav/footer, extracts name from h1, extracts all sections, records the subtype (condition or gene).

**Output:** `medlineplus_scraper/part5_genetics/output/genetics.json`

**Output schema per record:**
```
{
  "type": "genetics_condition",   ← or "genetics_gene"
  "name": "Cystic fibrosis",
  "url": "https://medlineplus.gov/genetics/condition/cystic-fibrosis/",
  "subtype": "condition",          ← "condition" or "gene"
  "sections": [
    {"heading": "Description", "content": "..."},
    {"heading": "Frequency", "content": "..."},
    {"heading": "Causes", "content": "..."},
    {"heading": "Inheritance", "content": "..."},
    {"heading": "Other names", "content": "..."}
  ],
  "status": "success",
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (chatbot-service)

---

## 4. Mayo Clinic Scrapers — 4 Parts

All Mayo Clinic scrapers use Playwright with stealth browser settings to navigate the site. Each page has multiple content tabs — the scraper navigates to each tab and extracts its content separately. This multi-tab extraction is what makes the Mayo Clinic data especially rich — a single disease page may have 8 tabs each with hundreds of words of content. The shared `utils.py` for Mayo Clinic provides: browser setup with anti-detection settings, safe navigation with retry logic, tab detection and navigation, content extraction per tab, link extraction from index pages, checkpoint/resume, and progress logging.

### 4.1 Part 1 — Diseases and Conditions

**Script:** `mayo_clinic/part1_diseases_conditions/scraper.py`

**Index pattern:** `https://www.mayoclinic.org/diseases-conditions/index?letter={A-Z}` — 26 pages, one per letter.

**URL filter:** Path must match `/diseases-conditions/{slug}/symptoms-causes/syc-{ID}` pattern. This identifies individual disease pages (not index pages or related links).

**Per-page extraction:** Navigate to the disease page, detect all available tabs, navigate to each tab in sequence, extract the full content of each tab. Typical tabs across diseases: Overview, Symptoms, Causes, Risk Factors, Complications, Prevention, Diagnosis, Treatment.

Not all diseases have all tabs — the scraper records only the tabs that exist for each disease.

**Output:** `mayo_clinic_scraper/part1_diseases_conditions/output/diseases_conditions.json`

**Output schema per record:**
```
{
  "name": "Migraine",
  "url": "https://www.mayoclinic.org/diseases-conditions/migraine-headache/symptoms-causes/syc-20360201",
  "status": "success",
  "sections": {
    "Symptoms": "Migraines, which affect children and teenagers...",
    "Causes": "Though migraine causes aren't fully understood...",
    "Risk Factors": "Several factors make you more prone to having migraines...",
    "Complications": "Taking pain-relieving medications too often can trigger...",
    "Diagnosis": "If you have migraines or a family history...",
    "Treatment": "Migraine treatment is aimed at stopping symptoms..."
  },
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (chatbot-service, symptom-service background info)

### 4.2 Part 2 — Symptoms

**Script:** `mayo_clinic/part2_symptoms/scraper.py`

**Index pattern:** `https://www.mayoclinic.org/symptoms/index?letter={A-Z}`

**URL filter:** Path must match `/symptoms/{slug}/basics/` pattern.

**Typical tabs:** Overview, Causes, When to see a doctor.

**Output:** `mayo_clinic_scraper/part2_symptoms/output/symptoms.json`

**Output schema per record:**
```
{
  "name": "Chest pain",
  "url": "https://www.mayoclinic.org/symptoms/chest-pain/basics/syc-20370885",
  "status": "success",
  "sections": {
    "Overview": "Chest pain appears in many forms, ranging from a sharp stab...",
    "Causes": "Chest pain has many possible causes, all of which deserve medical attention...",
    "When to see a doctor": "Seek emergency medical care immediately if you think..."
  },
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (chatbot-service, symptom-service background info)

### 4.3 Part 3 — Tests and Procedures

**Script:** `mayo_clinic/part3_tests_procedures/scraper.py`

**Index pattern:** `https://www.mayoclinic.org/tests-procedures/index?letter={A-Z}`

**URL filter:** Path must match `/tests-procedures/{slug}/(about/)?{pac|pyc}-{ID}` pattern.

**Typical tabs:** Overview, Why It's Done, Risks, How You Prepare, What You Can Expect, Results.

**Output:** `mayo_clinic_scraper/part3_tests_procedures/output/tests_procedures.json`

**Output schema per record:**
```
{
  "name": "MRI",
  "url": "https://www.mayoclinic.org/tests-procedures/mri/about/pac-20384768",
  "status": "success",
  "sections": {
    "Overview": "Magnetic resonance imaging (MRI) is a medical imaging technique...",
    "Why It's Done": "MRI is used to examine or detect a number of conditions...",
    "Risks": "MRI is a safe procedure for most people...",
    "How You Prepare": "Before an MRI, you'll likely need to change into a hospital gown...",
    "What You Can Expect": "During the MRI, you lie on a moveable table that slides into the opening...",
    "Results": "A radiologist analyzes the images and sends a report to your doctor..."
  },
  "scraped_at": "2025-..."
}
```

**Feeds:** Medical RAG (lab-service for test context, chatbot-service)

### 4.4 Part 4 — Drugs and Supplements

**Script:** `mayo_clinic/part4_drugs/scraper.py`

**Index pattern:** `https://www.mayoclinic.org/drugs-supplements/drug-list?letter={A-Z}`

**URL filter:** Path must match `/drugs-supplements/{slug}/description/drg-{ID}` pattern.

**Content extraction:** Mayo Clinic drug pages do not use tabs — they use section-based scrollable layout. The scraper extracts content by h2 section headings. Typical sections: Description, Before Using, Proper Use, Precautions, Side Effects.

**Output:** `mayo_clinic_scraper/part4_drugs/output/drugs_supplements.json`

**Output schema per record:**
```
{
  "name": "Ibuprofen (Oral Route)",
  "url": "https://www.mayoclinic.org/drugs-supplements/ibuprofen-oral-route/description/drg-20070820",
  "status": "success",
  "sections": {
    "Description": "Ibuprofen is used to relieve mild to moderate pain...",
    "Before Using": "In deciding to use a medicine, the risks of taking...",
    "Proper Use": "Take this medicine only as directed...",
    "Precautions": "It is very important that your doctor check your progress...",
    "Side Effects": "Along with its needed effects, ibuprofen may cause..."
  },
  "scraped_at": "2025-..."
}
```

**Feeds:** Drug RAG (drug-service, chatbot-service)

---

## 5. Infermedica API Scraper

**Script:** `data-pipeline/scrapers/infermedica_scraper.py`

**Credentials required:** `APP_ID` and `APP_KEY` from Infermedica Developer Portal. Set at top of script.

**Dev-Mode header:** All requests include `Dev-Mode: true` header. This excludes requests from Infermedica billing analytics so scraping does not consume paid quota.

**Rate limiting built in:** 0.5-second delay between every request, 2-second pause between batches of 20 detail requests. All errors are caught and logged — scraper never crashes on individual failures.

**What gets scraped — 7 stages:**

Stage 1 — `/info`: Model metadata (version, symptom count, condition count). Saved to `output/info.json`.

Stage 2 — `/symptoms` + `/symptoms/{id}`: All ~1,100 symptoms with full details per symptom (name, common_name, sex_filter, categories, body_locations, severity, extras). Saved to `output/symptoms.json`.

Stage 3 — `/conditions` + `/conditions/{id}`: All ~500 conditions with full details (name, common_name, sex_filter, categories, prevalence, severity, extras, acuteness). Saved to `output/conditions.json`.

Stage 4 — `/risk_factors` + `/risk_factors/{id}`: All ~40 risk factors with details. Saved to `output/risk_factors.json`.

Stage 5 — `/parse`: NLP extraction tested on 10 sample phrases (e.g. "I have a headache and fever"). Validates that /parse correctly maps text to symptom IDs. Saved to `output/parse_samples.json`.

Stage 6 — `/search`: Search index tested on 10 common medical terms. Saved to `output/search_samples.json`.

Stage 7 — Full diagnostic interview simulations: For each seed symptom (configurable: first 50 by default, or all ~1,100), for each sex (male, female), for each age sample (25, 40, 60), run a complete multi-turn interview simulation:
- POST `/diagnosis` with initial evidence → get first follow-up question
- Answer the question (deterministically — always choose the first available choice)
- POST `/diagnosis` again with updated evidence
- Repeat up to 15 turns or until `should_stop: true`
- After loop: POST `/triage` → POST `/explain` → POST `/specialist`
- Record the full conversation including every question, every answer, all conditions at each turn, final triage level, and explanation

**Most valuable output:** `output/diagnosis_flows.json` — each record is one complete simulated diagnostic interview with full conversation history, final conditions, triage level, and explanation data.

**Goes to:** Beta training pipeline via `infermedica_to_beta_training.py` — not into any RAG system.

---

## 6. EndlessMedical API Scraper

**Script:** `data-pipeline/scrapers/endlessmedical_scraper.py`

**No credentials required.** Fully public API. No API key, no account needed.

**Session management:** Every simulation requires its own session. The scraper: calls `/InitSession` → receives a `SessionID` → calls `/AcceptTermsOfUse` with the exact required passphrase (hardcoded in the script) → all subsequent calls for that session include the `SessionID` parameter.

**Rate limiting:** 0.6-second delay between every request, 2-second pause between full session simulations. All errors caught and logged.

**What gets scraped — 3 stages:**

Stage 1 — Metadata (no session needed):
- GET `/GetFeatures`: all feature names — symptoms, lab values, vital signs, medical history items. Saved to `output_endlessmedical/features.json`.
- GET `/GetOutcomes`: all disease/outcome names. Saved to `output_endlessmedical/outcomes.json`.

Stage 2 — Per-feature session simulations:
For each seed feature (configurable: first 50 by default, or all):
- InitSession + AcceptTermsOfUse → fresh SessionID
- POST `/UpdateFeature` — set the seed feature to a plausible value (1 for binary features, mid-range for continuous)
- For up to 8 turns:
  - GET `/GetSuggestedFeatures_PatientProvided` — next patient-reported features to add
  - GET `/GetSuggestedFeatures_PhysicianProvided` — next physician-assessed features
  - GET `/GetSuggestedTests` — recommended diagnostic tests
  - POST `/UpdateFeature` — add the top suggested patient feature
  - GET `/Analyze` — get differential diagnosis with disease probabilities + variable importances
  - Record everything from this turn
- Final GET `/Analyze` with all features set

Saved to `output_endlessmedical/feature_sessions.json`. Each record is one complete simulation flow showing how the differential evolves as more information is added.

Stage 3 — Multi-feature clinical combo simulations:
8 predefined clinical scenarios combining multiple symptoms:
- Chest pain + shortness of breath
- Fever + headache + stiff neck (meningitis pattern)
- Abdominal pain + nausea + vomiting
- Chest pain + sweating + jaw pain (cardiac pattern)
- Fatigue + weight loss + night sweats
- Joint pain + swelling + morning stiffness
- Confusion + headache + photophobia
- Urinary frequency + burning + fever

Each combo: InitSession → AcceptTermsOfUse → set all features → Analyze → record full differential diagnosis.

Saved to `output_endlessmedical/multi_feature_sessions.json`.

**Goes to:** Beta training pipeline only — not into any RAG system.

---

## 7. Text and Table Extraction — Per Source

### 7.1 Drugs.com PDFs (General and Professional)

**Text extraction tool:** PyMuPDF (fitz)

PyMuPDF opens each PDF file, iterates through all pages, and extracts the text content of each page. Each page's text is prefixed with a `[Page N]` marker so that chunk metadata can record which page a chunk came from. Pages that return empty or whitespace-only text are skipped. The extracted text from all pages is joined with double newlines between pages.

After raw extraction, a cleaning pass removes common PDF artifacts: page numbers appearing alone on a line, running headers/footers (detected as lines repeated across multiple pages), and encoding artifacts (non-UTF-8 characters replaced or removed).

**Table extraction tool:** pdfplumber (primary) + Camelot (secondary for complex tables)

pdfplumber is applied page by page to detect and extract tables. It uses two detection modes:
- Lattice mode: for tables with visible borders/lines (most common in professional drug PDFs — dosage tables, pharmacokinetic parameter tables)
- Stream mode: for tables without explicit borders, relying on whitespace alignment

When pdfplumber returns an empty result for a page that visually appears to contain a table, Camelot is applied as a secondary attempt with its own lattice extraction algorithm.

**Extracted table format:** Each table is converted to structured plain text for storage in RAG. The header row is preserved. Each data row is formatted as comma-separated `Header: Value` pairs. Example:
```
Patient Group: Adults | Initial Dose: 0.25 mcg/day | Maintenance Dose: 0.5-1 mcg/day
Patient Group: Dialysis | Initial Dose: 0.25 mcg/day | Maintenance Dose: 0.5-1 mcg/day
```
This format preserves the relationship between column headers and cell values even when the chunk is retrieved without its surrounding context.

**Section boundary detection:**
After text extraction, section headers are detected using a list of known medical document section names. Detection rules:
- Line is all-uppercase AND line length is under 60 characters AND followed by content → likely section header
- Line matches a known section name list (DOSAGE AND ADMINISTRATION, DRUG INTERACTIONS, PHARMACOKINETICS, CONTRAINDICATIONS, WARNINGS AND PRECAUTIONS, USE IN SPECIFIC POPULATIONS, INDICATIONS AND USAGE, CLINICAL PHARMACOLOGY, MECHANISM OF ACTION, DESCRIPTION, ADVERSE REACTIONS, OVERDOSAGE, HOW SUPPLIED, CARCINOGENESIS, PREGNANCY, NURSING MOTHERS, PEDIATRIC USE, GERIATRIC USE, DRUG INTERACTIONS) → confirmed section header

Each detected section boundary is marked in the text before chunking so the chunker knows where to split first.

**Structured field extraction (deep extraction — Stage 3):**
After text extraction, a deep extraction pass uses regex patterns to pull out structured numeric values from the raw text. These are stored in a `structured_fields` JSON object alongside the text content:
- Dosage values: mg, mcg, ng per day/kg
- Half-life: hours
- Molecular weight
- Protein binding percentage
- Peak serum concentration: hours
- Storage temperature range
- Contraindication keywords (hypercalcemia, hypersensitivity, etc.)
- Warning keywords
- Drug class identification

Structured fields are stored in chunk metadata and also in the PostgreSQL drug data table for direct lookup without RAG retrieval.

### 7.2 MedlinePlus Scraped Data (All 5 Parts)

**No additional extraction step needed.** The MedlinePlus scrapers (`scraper.py` files using BeautifulSoup + requests) already produce clean structured JSON output. The `extract_sections()` function in `utils.py` runs during scraping and produces the `sections: [{heading, content}]` structure.

The only post-processing needed before chunking:
- Normalize Unicode text (NFKC normalization, remove \xa0 non-breaking spaces, collapse whitespace)
- Re-parse any HTML tables that appear inside section content: detect pipe-formatted or aligned text, convert to the same `Header: Value` pair format used for drug PDF tables
- Validate that `content` fields are non-empty — records with empty sections are flagged and skipped

### 7.3 Mayo Clinic Scraped Data (All 4 Parts)

**No additional extraction step needed.** The Mayo Clinic scrapers already produce structured JSON with `sections` organized by tab name (or section name for drugs). Each tab content is a clean string of medical text already free of navigation and boilerplate (stripped by Playwright-rendered HTML cleaning).

Post-processing before chunking:
- Same Unicode normalization as MedlinePlus
- Section content that contains embedded lists: detect and normalize to bullet format for consistent chunking
- Sections with zero meaningful content (e.g. tabs that only contain "Loading..." or navigation artifacts): detected by content length threshold (< 50 characters) and excluded

### 7.4 Research Papers (User Uploaded or Agent Downloaded)

**Digital PDFs (selectable text):**
PyMuPDF extracts text page by page with `[Page N]` markers. pdfplumber additionally extracts tables from each page.

**Section detection in research papers:**
Academic papers follow less consistent formatting than medical PDFs. Section detection uses a combination of:
- Font size analysis: text blocks with larger or bolder font properties detected as potential headings
- Common section name matching: Abstract, Introduction, Background, Methods, Methodology, Materials, Results, Findings, Discussion, Conclusion, Conclusions, References, Bibliography, Acknowledgements, Appendix
- Numbering patterns: "1.", "1.1", "I.", "II." at the start of a line followed by a short capitalized phrase

**Scanned PDFs and images:**
If PyMuPDF returns fewer than 50 meaningful characters per page across the document, the PDF is classified as scanned. The configured OCR engine processes it (PaddleOCR → Mistral → LightOn → LLM-based in fallback order). OCR is run per page. Results are assembled in page order.

**DOCX files:**
python-docx extracts text paragraph by paragraph. Headings are identified by paragraph style name (Heading 1, Heading 2, etc.). Tables are extracted row by row in the same `Header: Value` format.

**Table and figure handling:**
Tables in research papers: pdfplumber with both lattice and stream modes. Figures: only the caption text is extracted (text near "Figure N:" or "Fig. N:" patterns). The image pixel content is not stored in RAG — only the caption.

---

## 8. Chunking Strategies — Per Source

The default chunking approach across all sources: detect section boundaries first, create one chunk per section if it fits within the token limit, apply semantic sub-chunking within sections that exceed the limit. This hybrid approach preserves the logical grouping of medical content while ensuring no chunk exceeds the embedding model's effective context window.

### 8.1 Chunking Infrastructure (from `shared/chunking/`)

**Token counting:** tiktoken with `cl100k_base` encoding is used for all token counting. This encoding is consistent with most major LLM providers and embedding models.

**Sentence boundary respect:** When sub-chunking within a section, NLTK sentence tokenizer is used to prevent splitting in the middle of a sentence. Chunks always begin and end at sentence boundaries.

**Overlap:** When a section is too large and split into multiple semantic sub-chunks, the last N tokens of one sub-chunk are repeated at the start of the next. This overlap preserves context across chunk boundaries — a question answered across a sentence boundary can still be retrieved correctly.

**Tables:** Tables are always stored as single chunks regardless of size. They are never split across multiple chunks. If a table is very large (rare but possible in professional drug PDFs), it may exceed the target chunk size — this is acceptable. The alternative (splitting a dosage table in half) would render the chunk useless.

**Metadata attached to every chunk:**
All chunks regardless of source carry at minimum: `source`, `content_type`, `url`, `chunk_index`, `token_count`, `chunk_type` (text or table), `heading` or `section`. Source-specific fields are added on top of these.

---

### 8.2 Drugs.com Professional PDFs

**Target chunk size:** 300–512 tokens
**Overlap between sub-chunks:** 50 tokens
**Table handling:** Always one chunk

**Primary split — named medical sections:**
The following section names trigger a new chunk boundary. Each section becomes the start of a new chunk group. If the section content fits within the target size it is one chunk. If it exceeds the target, it is semantically sub-chunked into multiple chunks all sharing the same section name in metadata.

Section list triggering splits:
- DESCRIPTION
- CLINICAL PHARMACOLOGY / MECHANISM OF ACTION
- PHARMACOKINETICS (including sub-sections: Absorption, Distribution, Metabolism, Excretion)
- INDICATIONS AND USAGE
- CONTRAINDICATIONS
- WARNINGS AND PRECAUTIONS
- ADVERSE REACTIONS
- DRUG INTERACTIONS
- USE IN SPECIFIC POPULATIONS (including sub-sections: Pregnancy, Nursing Mothers, Pediatric Use, Geriatric Use)
- DOSAGE AND ADMINISTRATION
- OVERDOSAGE
- HOW SUPPLIED
- CARCINOGENESIS, MUTAGENESIS, IMPAIRMENT OF FERTILITY
- REFERENCES

**Secondary split — semantic sub-chunking:**
If any section's content exceeds 512 tokens, NLTK sentence tokenizer identifies sentence boundaries within the section. The section is divided into sub-chunks of 300–400 tokens with 50-token overlap. All sub-chunks carry the same `section_name` in metadata.

**Metadata per chunk:**
```
drug_name:    "acetaminophen"
rxcui:        "161"           ← populated after RxNorm normalization
source:       "drugs.com"
source_type:  "professional"  ← or "general"
section_name: "PHARMACOKINETICS"
page_number:  4
chunk_type:   "text"          ← or "table"
chunk_index:  7
token_count:  342
url:          "https://www.drugs.com/pro/acetaminophen"
```

### 8.3 Drugs.com General PDFs

**Target chunk size:** 250–400 tokens
**Overlap:** 50 tokens

**Primary split — patient-facing section names:**
Patient-facing drug pages use different section naming than professional inserts. The chunker detects these section patterns:
- What is [drug name]?
- Uses / What is this medication used for?
- Warnings
- Before taking / Before using
- How to use / Dosage / How should I use this medicine?
- Side effects / What side effects may I notice?
- Drug interactions / What may interact with this medicine?
- Missed dose
- Storage / How should I store this medicine?
- Notes / Important information

**Secondary split:** Same semantic sub-chunking approach as professional PDFs when section exceeds 400 tokens.

**Metadata per chunk:**
```
drug_name:    "ibuprofen"
rxcui:        "5640"
source:       "drugs.com"
source_type:  "general"
section_name: "Side effects"
chunk_type:   "text"
```

### 8.4 MedlinePlus Health Topics

**Target chunk size:** 200–400 tokens
**Overlap:** 40 tokens

**Primary split — by h2/h3 heading:**
The scrapers already produce `sections: [{heading, content}]`. Each heading-content pair is one chunk group. The heading itself is prepended to the content text in the chunk so that the chunk is self-contained: a chunk starting with "Treatments and Therapies" includes those three words before the treatment text.

**Secondary split — semantic within long sections:**
Sections exceeding 400 tokens are semantically sub-chunked. Common in broad topics like "Treatments and Therapies" which may list many different treatments.

**Bullet list handling:**
Content that is a list of bullet items (from `• item` format produced by the scraper's list extraction) is kept together as one chunk if it fits within 400 tokens. If the bullet list exceeds 400 tokens, it is split at bullet boundaries (never mid-bullet).

**Metadata per chunk:**
```
topic_name:    "Headache"
source:        "medlineplus"
content_type:  "health_topic"
url:           "https://medlineplus.gov/headache.html"
heading:       "Treatments and Therapies"
also_known_as: ["Head pain", "Cephalalgia"]
chunk_type:    "text"
```

### 8.5 MedlinePlus Drugs

**Target chunk size:** 250–400 tokens
**Overlap:** 40 tokens

**Primary split — by section heading:**
Each section from the scraped JSON (Why is this prescribed? / How to use / Side effects / Precautions / Missed dose / Storage) becomes a chunk group.

**Critical rule — reference ranges and dosage sections:**
Never split the "How should this medicine be used?" section mid-dose. If dosage instructions list multiple conditions or age groups, keep related dosage guidance together. A reader asking "what is the dose of X for children?" needs the pediatric dosage in one retrievable chunk.

**Secondary split:** Semantic when section exceeds 400 tokens.

**Metadata per chunk:**
```
drug_name:    "ibuprofen"
rxcui:        "5640"
source:       "medlineplus"
content_type: "drug"
url:          "https://medlineplus.gov/druginfo/meds/a682159.html"
section:      "Side effects"
```

### 8.6 MedlinePlus Lab Tests

**Target chunk size:** 200–350 tokens
**Overlap:** 30 tokens

**Primary split — by test and by section within test:**
Each lab test page produces chunk groups organized by section. Sections are treated individually.

**Critical rule — reference ranges must never be separated from test identity:**
The section containing normal/reference range values must always be in the same chunk as the test name context. When chunking the "What do the results mean?" section, ensure the test name appears in the chunk text (prepend it if necessary). A retrieved chunk must always make clear which test it refers to and what the normal range is.

**Secondary split:** Semantic when section exceeds 350 tokens, but always preserve any sentence mentioning a specific numeric range as a complete unit — never split "Normal values are 4.5 to 5.5 million cells/mcL" across two chunks.

**Metadata per chunk:**
```
test_name:    "Complete Blood Count (CBC)"
source:       "medlineplus"
content_type: "lab_test"
url:          "https://medlineplus.gov/lab-tests/complete-blood-count/"
section:      "What do the results mean?"
```

### 8.7 MedlinePlus Encyclopedia

**Target chunk size:** 250–400 tokens
**Overlap:** 40 tokens

**Primary split:** By h2/h3 heading — same approach as health topics.

**Metadata per chunk:**
```
article_name:  "Liver biopsy"
source:        "medlineplus"
content_type:  "encyclopedia"
url:           "https://medlineplus.gov/ency/article/003895.htm"
heading:       "Normal Results"
```

### 8.8 MedlinePlus Genetics

**Target chunk size:** 250–450 tokens (genetics content tends to be denser)
**Overlap:** 50 tokens

**Primary split:** By section heading.

**Metadata per chunk:**
```
name:         "Cystic fibrosis"
subtype:      "condition"
source:       "medlineplus"
content_type: "genetics"
url:          "https://medlineplus.gov/genetics/condition/cystic-fibrosis/"
section:      "Inheritance"
```

### 8.9 Mayo Clinic Diseases and Conditions

**Target chunk size:** 300–500 tokens
**Overlap:** 60 tokens (longer overlap because disease content is dense and interconnected)

**Primary split — by tab:**
Each tab from the scraped JSON is one chunk group. Tab names are: Symptoms, Causes, Risk Factors, Complications, Prevention, Diagnosis, Treatment.

**The tab name is always the first line of the chunk text** — this is critical. A chunk starting with "Treatment\n\nMigraine treatment is aimed at..." is self-contained and unambiguous when retrieved.

**Secondary split — semantic within long tabs:**
Treatment and Diagnosis tabs are commonly very long (1000+ tokens). They are semantically sub-chunked. All sub-chunks carry the same tab name in metadata.

**Metadata per chunk:**
```
condition_name: "Migraine"
source:         "mayo_clinic"
content_type:   "disease_condition"
url:            "https://www.mayoclinic.org/diseases-conditions/migraine-headache/..."
tab_name:       "Treatment"
chunk_index:    2
```

### 8.10 Mayo Clinic Symptoms

**Target chunk size:** 250–400 tokens
**Overlap:** 40 tokens

**Primary split — by tab:**
Tabs: Overview, Causes, When to see a doctor.

**Metadata per chunk:**
```
symptom_name: "Chest pain"
source:       "mayo_clinic"
content_type: "symptom"
url:          "..."
tab_name:     "Causes"
```

### 8.11 Mayo Clinic Tests and Procedures

**Target chunk size:** 250–450 tokens
**Overlap:** 50 tokens

**Primary split — by tab:**
Tabs: Overview, Why It's Done, Risks, How You Prepare, What You Can Expect, Results.

**Metadata per chunk:**
```
test_name:    "MRI"
source:       "mayo_clinic"
content_type: "test_procedure"
url:          "..."
tab_name:     "What You Can Expect"
```

### 8.12 Mayo Clinic Drugs and Supplements

**Target chunk size:** 250–400 tokens
**Overlap:** 40 tokens

**Primary split — by section heading:**
Sections: Description, Before Using, Proper Use, Precautions, Side Effects.

**Tables within drug pages:** Stored as single chunks with table-type metadata.

**Metadata per chunk:**
```
drug_name:    "Ibuprofen (Oral Route)"
source:       "mayo_clinic"
content_type: "drug"
url:          "..."
section:      "Precautions"
```

---

### 8.13 DDIMDL Drug-Drug Interactions (DrugBank 5.1.3)

**Target chunk size:** 1 chunk per interaction record — no splitting needed (interaction sentences are 15–30 tokens each)
**Overlap:** Not applicable — single-chunk records

**Source:** `Interactions.csv` — 37,264 records from DrugBank 5.1.3, published in Deng et al., *Bioinformatics*, 2020.

**Chunk text format:**
Every interaction is stored with both drug names prepended to the sentence so the chunk is fully self-identifying when retrieved without surrounding context:

```
{drug_a_name} + {drug_b_name} drug interaction:
{interaction_text}
```

Example:
```
Abemaciclib + Amiodarone drug interaction:
The risk or severity of adverse effects can be increased when Abemaciclib is combined with Amiodarone.
```

**Mechanism type classification (deterministic keyword detection — not LLM):**
Each interaction text is classified before embedding using keyword matching:
- `serum_concentration` — text contains "serum concentration" (8,356 records)
- `metabolism` — text contains "metabolism of" (10,505 records)
- `risk_adverse` — text contains "risk or severity of adverse" (9,496 records)
- `therapeutic_efficacy` — text contains "therapeutic efficacy" (1,477 records)
- `anticoagulant` — text contains "anticoagulant" (373 records)
- `hypoglycemic` — text contains "hypoglycemic" (362 records)
- `neuromuscular` — text contains "neuromuscular" (6 records)
- `other` — none of the above (remaining records)

**Metadata per chunk:**
```
source:           "ddimdl"
section_name:     "DRUG INTERACTIONS"
drug_a:           "Abemaciclib"
drug_b:           "Amiodarone"
drugbank_id_a:    "DB12001"
drugbank_id_b:    "DB01118"
rxcui_a:          "..."     (populated after RxNorm resolution)
rxcui_b:          "..."
mechanism_type:   "risk_adverse"
chunk_type:       "text"
source_citation:  "Deng et al., Bioinformatics, 2020. DrugBank 5.1.3."
```

**Important note on pair directionality:** The `drugbank_id_a` is always the lexicographically smaller DrugBank ID between the two. This ensures that the pair (DB12001, DB01118) and its reverse (DB01118, DB12001) share the same canonical representation and hit the same cache entry and PostgreSQL lookup.

**These chunks participate in all Drug RAG searches with `section_name: DRUG INTERACTIONS` filter.** Because DDIMDL chunks use the same section name as Drugs.com interaction chunks, they are retrieved together in the same Qdrant search — giving the retrieval system 37,264 additional high-quality interaction sentences from DrugBank on top of the Drugs.com content.

### 8.13 Research Papers (Per-Session)

**Target chunk size:** 400–600 tokens (larger because research papers require more context per chunk)
**Overlap:** 80 tokens (larger overlap — research queries often span section boundaries)

**Primary split — by paper section:**
Sections: Abstract, Introduction, Background, Methods, Methodology, Results, Findings, Discussion, Conclusion, Conclusions, Limitations, References.

**The section name is always prepended to the chunk text.**

**Secondary split:** Semantic sub-chunking within long sections (Methods and Results are commonly 2000+ tokens in long papers).

**Tables:** One chunk each. The table caption is prepended to the table content. Format: `Table N: {caption}\n{structured table text}`.

**Figure captions:** Stored as their own chunks. Format: `Figure N: {caption}`. The chunk signals to the LLM that there is a figure here described by the caption text. The image itself is not stored.

**References section:** The references section is stored in RAG if it contains named references that might be cited in retrieved content — but given high token cost and low query value, the references section is chunked at the citation level (one chunk per 5–10 citations grouped by subject). Retrieved only when a user explicitly asks about references or sources.

**Metadata per chunk:**
```
paper_title:  "Machine learning approaches for predicting drug-drug interactions"
doi:          "10.1016/j.jbi.2021.103757"
authors:      ["Smith J", "Chen L", "Patel R"]
year:         2021
session_id:   "uuid-of-session"
section:      "Results"
page_range:   "8-12"
chunk_type:   "text"    ← or "table" or "figure_caption"
chunk_index:  15
token_count:  487
```

---

## 9. Three RAG Systems

MAISYS operates three independent RAG systems. Each has its own Qdrant collections, ingestion pipeline, chunking configuration, and set of consuming services.

### 9.1 Medical RAG

**Purpose:** General medical knowledge base covering diseases, symptoms, conditions, lab tests, medical procedures, anatomy, genetics, and health guidance.

**Sources ingested:**
- MedlinePlus health topics (~1,060 topics)
- MedlinePlus lab tests (~1,000+ tests)
- MedlinePlus encyclopedia (~40,000 articles)
- MedlinePlus genetics (conditions + genes)
- Mayo Clinic diseases and conditions (A–Z)
- Mayo Clinic symptoms (A–Z)
- Mayo Clinic tests and procedures (A–Z)

**Qdrant collections:**
- `medical_minilm` — all Medical RAG chunks embedded with all-MiniLM-L6-v2 (384-dim)
- `medical_pubmedbert` — same chunks embedded with PubMedBERT (768-dim)

**Consumed by:** chatbot-service (all queries), lab-service (test enrichment), symptom-service (background disease/symptom info alongside Infermedica results)

**Section filters available:**
- lab-service queries filter by `content_type: "lab_test"` to retrieve only lab test content
- symptom-service queries filter by `content_type: "disease_condition"` or `content_type: "symptom"` for background context
- chatbot-service applies no filter by default (searches all Medical RAG content)

### 9.2 Drug RAG

**Purpose:** Comprehensive drug knowledge base covering detailed clinical and patient-facing information, pharmacokinetics, interactions, dosing, and drug class information from multiple trusted sources.

**Sources ingested:**
- Drugs.com general PDFs (17,432 drugs — patient-facing)
- Drugs.com professional PDFs (6,450+ drugs — clinical/prescribing)
- MedlinePlus drugs (consumer drug information, brand/generic mappings)
- Mayo Clinic drugs and supplements (clinical drug descriptions)
- DDIMDL Interactions — 37,264 drug-drug interaction sentences from DrugBank 5.1.3, embedded as one chunk per pair (source: Deng et al., Bioinformatics, 2020)

**Qdrant collections:**
- `drug_minilm` — all Drug RAG chunks embedded with all-MiniLM-L6-v2 (384-dim)
- `drug_pubmedbert` — same chunks embedded with PubMedBERT (768-dim)

**Section filters used per drug feature:**

| Feature | Section Filter Applied |
|---|---|
| Drug profile lookup | No filter — all sections |
| Drug-drug interaction | `section_name: "DRUG INTERACTIONS"` — matches both Drugs.com sections and DDIMDL chunks |
| Drug-food interaction | `section_name: "DRUG INTERACTIONS"` + food keyword filter |
| Drug-disease contraindication | `section_name: "CONTRAINDICATIONS"` |
| Dosage calculator | `section_name: "DOSAGE AND ADMINISTRATION"` |
| Pharmacokinetics viewer | `section_name: "PHARMACOKINETICS"` |
| Pregnancy safety | `section_name: "USE IN SPECIFIC POPULATIONS"` |
| Off-label use | `section_name: "INDICATIONS AND USAGE"` |
| Drug comparison | All sections |
| Drug alternatives | All sections |

**DDIMDL chunk metadata stored in Qdrant:**
Each of the 37,264 DDIMDL interaction records is stored with: `source: ddimdl`, `section_name: DRUG INTERACTIONS`, `drug_a`, `drug_b`, `drugbank_id_a`, `drugbank_id_b`, `rxcui_a`, `rxcui_b`, `mechanism_type` (serum_concentration / metabolism / risk_adverse / therapeutic_efficacy / anticoagulant / hypoglycemic / neuromuscular / other).

**Consumed by:** drug-service (primary, section-filtered queries), chatbot-service (when question involves drug information — searched in addition to Medical RAG)

### 9.3 Paper RAG

**Purpose:** Per-session research paper knowledge base. Each research session creates its own isolated Qdrant collection for the papers in that session. Questions about papers are answered by searching only the papers in the active session.

**Collection naming:** `papers_{session_id}` where session_id is the research session UUID.

**Sources:** User-uploaded PDFs/DOCX and papers downloaded by the Paper Discovery Agent.

**Lifecycle:**
- Created when first paper is ingested into a session
- Updated each time a new paper is added to the session
- Searched only when the user asks questions in chat or runs tools (summary, comparison, QA, translation)
- Destroyed when the session is deleted

**Qdrant collections (per session):**
- `papers_{session_id}_minilm` — paper chunks with MiniLM embeddings
- `papers_{session_id}_pubmedbert` — paper chunks with PubMedBERT embeddings

**Section filters:**
When a user asks for a summary, the system queries `section: "Abstract"` first for a quick overview, then retrieves from all sections for full summary generation.
When generating a comparison, each paper's sections are retrieved separately and compared section by section.

**Consumed by:** research-service only

---

## 10. Qdrant Collections — Full Schema

### 10.1 Medical RAG Collections

**Collection names:** `medical_minilm`, `medical_pubmedbert`

**Vector dimensions:**
- `medical_minilm`: 384 (all-MiniLM-L6-v2)
- `medical_pubmedbert`: 768 (PubMedBERT)

**Payload schema (fields stored with each vector):**
```
id:            string (UUID — same ID used in both collections for deduplication)
text:          string (the chunk text — used in LLM prompt construction)
source:        string ("medlineplus" | "mayo_clinic")
content_type:  string ("health_topic" | "lab_test" | "encyclopedia" | "genetics" |
                        "disease_condition" | "symptom" | "test_procedure")
subtype:       string (for genetics: "condition" | "gene")
name:          string (topic name / test name / condition name / article name)
url:           string (original source URL for citation)
heading:       string (h2/h3 heading or tab name — the section this chunk belongs to)
also_known_as: list[string] (for health topics with aliases)
chunk_index:   integer
token_count:   integer
chunk_type:    string ("text" | "table")
scraped_at:    string (ISO timestamp)
```

**Indexed payload fields (filterable in Qdrant):**
- `content_type` — for lab-service and symptom-service filtered queries
- `source` — for source-specific retrieval if needed
- `name` — for direct name-based lookup

### 10.2 Drug RAG Collections

**Collection names:** `drug_minilm`, `drug_pubmedbert`

**Vector dimensions:**
- `drug_minilm`: 384
- `drug_pubmedbert`: 768

**Payload schema:**
```
id:           string (UUID — same in both collections)
text:         string (chunk text)
source:       string ("drugs.com" | "medlineplus" | "mayo_clinic")
source_type:  string ("professional" | "general" | "drug" — for drugs.com source)
drug_name:    string (canonical drug name)
rxcui:        string (RxNorm CUI — populated after normalization step)
section_name: string (medical section name: "DRUG INTERACTIONS", "PHARMACOKINETICS", etc.)
url:          string (source URL for citation)
page_number:  integer (for PDFs — which page the chunk came from)
chunk_index:  integer
token_count:  integer
chunk_type:   string ("text" | "table")
scraped_at:   string
```

**Indexed payload fields:**
- `section_name` — primary filter for drug feature-specific queries
- `drug_name` — for drug-specific direct retrieval
- `rxcui` — for normalized drug lookup
- `source_type` — to prioritize professional vs general content

### 10.3 Paper RAG Collections (Per Session)

**Collection names:** `papers_{session_id}_minilm`, `papers_{session_id}_pubmedbert`

**Vector dimensions:** same as above (384 / 768)

**Payload schema:**
```
id:          string
text:        string (chunk text)
paper_id:    string (UUID of paper in research-service PostgreSQL)
paper_title: string
doi:         string (if available)
authors:     list[string]
year:        integer (if available)
section:     string ("Abstract" | "Introduction" | "Methods" | "Results" | "Discussion" | "Conclusion" | etc.)
page_range:  string (e.g. "4-7")
chunk_index: integer
token_count: integer
chunk_type:  string ("text" | "table" | "figure_caption")
session_id:  string (research session UUID)
```

**Indexed payload fields:**
- `paper_id` — filter to search within a specific paper
- `section` — filter for section-specific queries (abstract-first for summaries)
- `chunk_type` — filter to retrieve only tables or only text

---

## 11. Dual Embedding Pipeline

### 11.1 Why Two Embedding Models

Every chunk in every RAG system is embedded twice — once with each model. Both collections are always searched in parallel. Results are merged and deduplicated before being passed to the LLM.

**all-MiniLM-L6-v2** excels at general semantic similarity. It handles natural language questions well — "what are the side effects of ibuprofen?" maps effectively to relevant side effects content even though the chunk text may use different phrasing.

**PubMedBERT** was pre-trained on PubMed biomedical literature. It understands medical terminology, drug names, disease names, and clinical language at a deeper level than a general embedding model. A query about "CYP3A4 metabolism" or "eGFR-based dosing" will retrieve more precise results from PubMedBERT embeddings than from MiniLM.

Using both ensures that both plain-language patient queries and precise clinical terminology queries retrieve the best possible chunks.

### 11.2 Dual Search and Merge Process

**Step 1 — Parallel search:**
Both Qdrant collections are searched simultaneously using asyncio.gather. The same query text is independently embedded by each model and searched in the corresponding collection. Both searches use the same payload filter (if any).

**Step 2 — Merge:**
Results from both collections are combined into a single list. Results are keyed by their chunk `id` field (same UUID across both collections for the same chunk content).

**Step 3 — Deduplication:**
When the same chunk ID appears in both result sets, keep the result with the higher similarity score. Discard the duplicate.

**Step 4 — Re-ranking:**
The merged and deduplicated list is sorted by score descending. Top K results (default: 8 for Drug RAG, 6 for Medical RAG, 5 for Paper RAG) are returned.

**Step 5 — Sufficiency evaluation:**
The returned chunks are evaluated before being passed to the LLM. See Section 13 for sufficiency evaluation logic.

### 11.3 Query Embedding

When a user sends a query, the query text is embedded with both models simultaneously (asyncio.gather). The two resulting vectors are used independently to search their respective collections. The query is never modified before embedding — the raw user query (after translation to English if needed) is embedded as-is.

### 11.4 Embedding Model Loading

Both models are loaded at service startup and held in memory for the lifetime of the service. They are never reloaded per request. Loading happens once in the service's `startup` event handler and stored as singleton instances. This initialization adds approximately 2–5 seconds to startup time but eliminates per-request model loading overhead.

---

## 12. Ingestion Pipelines — Per Module

### 12.1 Drug RAG Ingestion

**Entry point:** `services/drug-service/ingestion/run_drug_ingestion.py`

**Ingestion order:**
1. Drugs.com professional PDFs (`ingest_drugs_pdfs.py` with `source_type=professional`)
2. Drugs.com general PDFs (`ingest_drugs_pdfs.py` with `source_type=general`)
3. MedlinePlus drugs (`ingest_medlineplus_drugs.py`)
4. Mayo Clinic drugs (`ingest_mayo_drugs.py`)
5. DDIMDL data (`ingest_ddimdl.py`) — processes both CSVs into PostgreSQL + Qdrant

**Per-drug ingestion flow (for PDFs):**
1. Read PDF file bytes from the organized folder structure
2. Run PyMuPDF text extraction with page markers
3. Run pdfplumber table extraction (Camelot fallback for complex tables)
4. Detect section boundaries in extracted text
5. Apply deep structured field extraction (dosage, half-life, contraindications, etc.)
6. Run medical-aware chunker: section-aware first → semantic within sections
7. For each chunk: embed with MiniLM → embed with PubMedBERT (both in parallel)
8. RxNorm normalization: look up drug name → get RxCUI → store in chunk metadata
9. Upsert to `drug_minilm` and `drug_pubmedbert` collections in Qdrant
10. Write drug record to PostgreSQL drug table (name, rxcui, structured_fields, source)

**Per-drug ingestion flow (for JSON — MedlinePlus and Mayo Clinic drugs):**
1. Load JSON record from scraped output file
2. Validate record (status == success, sections not empty)
3. Run drug-aware chunker on each section
4. For each chunk: dual embed
5. RxNorm normalization (match drug name → RxCUI)
6. Upsert to Qdrant
7. Write to PostgreSQL

**Batch processing:** PDFs are processed in concurrent batches of 10 using `shared/concurrent/batch_processor.py`. Progress is reported after each batch. Checkpoint saved every 100 drugs — if ingestion is interrupted, it resumes from the last checkpoint.

**Expected total volume:**
- Drugs.com professional: ~6,450+ PDF chunks (estimated 50–200 chunks per drug depending on document length) = several hundred thousand chunks
- Drugs.com general: ~17,432 PDFs (estimated 20–80 chunks per drug) = over a million chunks total
- MedlinePlus drugs: estimated 30–60 chunks per drug
- Mayo Clinic drugs: estimated 10–30 chunks per drug

### 12.2 Medical RAG Ingestion

**Entry point:** `services/chatbot-service/ingestion/run_all_ingestion.py`

**Ingestion order:**
1. MedlinePlus health topics (`ingest_medlineplus.py` with type=health_topics)
2. MedlinePlus lab tests (type=lab_tests)
3. MedlinePlus encyclopedia (type=encyclopedia)
4. MedlinePlus genetics (type=genetics)
5. Mayo Clinic diseases and conditions (`ingest_mayo_clinic.py` with type=diseases)
6. Mayo Clinic symptoms (type=symptoms)
7. Mayo Clinic tests and procedures (type=tests_procedures)

**Per-record ingestion flow (for JSON — all Medical RAG sources):**
1. Load JSON record from scraped output file
2. Validate (status == success, sections not empty)
3. Run source-appropriate chunker (section-based chunking configured per source type)
4. For each chunk: dual embed with MiniLM + PubMedBERT
5. Upsert to `medical_minilm` and `medical_pubmedbert` in Qdrant

**Batch processing:** Records processed in concurrent batches of 20. Checkpoint every 200 records.

### 12.3 Paper RAG Ingestion (Per Session — On Demand)

**Triggered by:** User uploading a paper OR Paper Discovery Agent successfully downloading a paper.

**Not a batch job** — happens in real time as each paper is added to a session.

**Flow:**
1. Receive file (PDF/DOCX) or download PDF from URL
2. Detect file type (digital PDF → PyMuPDF direct; scanned PDF or image → OCR pipeline)
3. Extract text (and tables) from all pages
4. Detect paper sections by heading analysis
5. Run paper chunker (400–600 token targets, 80-token overlap, section-aware)
6. For each chunk: dual embed with MiniLM + PubMedBERT
7. Upsert to `papers_{session_id}_minilm` and `papers_{session_id}_pubmedbert`
8. Write paper record to PostgreSQL research-service database
9. Publish progress events to WebSocket: "Processing paper 1: extracting text..." → "Indexing 47 chunks into your workspace..."

**Collection creation:** If the session's Qdrant collection does not yet exist, it is created before the first upsert. Vector size and distance metric are configured on creation (cosine distance for both MiniLM and PubMedBERT collections).

---

## 13. Sufficiency Evaluation

Before passing retrieved chunks to the LLM for response generation, the retrieval router evaluates whether the returned results are sufficient to generate a reliable answer. If evaluation fails, the system escalates to Tier 2 (web search or live scrape).

### 13.1 Two-Gate Evaluation

Both gates must pass for Tier 1 to proceed.

**Gate 1 — Chunk count:**
Minimum number of relevant chunks returned from Qdrant: `MIN_CHUNKS = 3` (configurable via environment variable). If fewer than 3 chunks are returned after deduplication, Tier 1 is considered insufficient regardless of their content. Rationale: fewer than 3 chunks indicates the knowledge base has minimal coverage of this drug or topic.

**Gate 2 — LLM confidence:**
A quick LLM call evaluates the retrieved chunks against the user query and returns a structured confidence score (0.0–1.0) alongside a brief reasoning. Minimum confidence threshold: `MIN_CONFIDENCE = 0.75`. If the LLM rates its confidence below 0.75, the chunks are considered insufficient.

The confidence prompt asks the LLM to honestly assess: "Based only on these retrieved documents, how fully can you answer this question? Score 0.0–1.0 where 1.0 means the documents contain everything needed for a complete accurate answer."

Importantly, this is a brief, low-temperature call using a small fast model (not the primary medical LLM) to minimize latency overhead on the evaluation step.

### 13.2 Evaluation Thresholds by Feature

Some features have adjusted thresholds because the consequences of insufficient data differ:

| Feature | MIN_CHUNKS | MIN_CONFIDENCE |
|---|---|---|
| Drug-drug interaction | 3 | 0.75 |
| Drug profile lookup | 3 | 0.70 (some drugs have sparse coverage) |
| Pharmacokinetics | 2 | 0.80 (PK data is very specific) |
| Dosage calculator | 2 | 0.85 (dosing errors are high risk) |
| General medical question | 3 | 0.70 |
| Lab test explanation | 2 | 0.65 (LLM has strong base knowledge here) |

### 13.3 What Happens When Both Gates Pass

The retrieved chunks are compiled into a context block and passed to the primary medical LLM for response generation. The response is generated with full streaming. Citations are extracted from chunk metadata (source, name, URL, section) and appended to the response.

Response is labeled: `source_tier: "local"`, `source_label: "✅ Local Knowledge Base"`.

### 13.4 What Happens When Either Gate Fails

Tier 2 is activated. The failure reason is logged: `chunk_count_below_threshold` or `llm_confidence_below_threshold`.

A progress event is published: for drug-drug interactions, "Checking Drugs.com for detailed interaction data..." — for other features, "Searching the web for additional information..."

See Section 14 for Tier 2 behavior.

---

## 14. Two-Tier Retrieval Pattern

### 14.1 Tier 2 — Drug-Drug Interactions: Drugs.com Live Agent

**Activated when:** Drug RAG returns insufficient results for a drug-drug interaction request.

**Agent flow:**
1. Playwright (headless Chromium) navigates to `https://www.drugs.com/drug_interactions.html`
2. For each drug in the user's request: locate the drug name input field, type the drug name, wait for autocomplete to appear, select or confirm the drug
3. After all drugs are entered: click the "Check Interactions" button
4. Wait for the interaction results panel to appear in the DOM (up to 20-second timeout)
5. Extract the full rendered page content of the results panel using BeautifulSoup: for each interaction pair, extract severity level (major/moderate/minor/contraindicated), drug pair names, interaction description, clinical significance, and recommendation
6. Assemble structured results — same format as Tier 1 responses
7. Pass to medical LLM for formatting and plain-language explanation generation
8. Response labeled: `source_tier: "web"`, `source_label: "🌐 Drugs.com"`, citation URL: `https://www.drugs.com/drug_interactions.html`
9. Cache result in Redis for 6 hours (key: `web_interaction:{rxcui_a}:{rxcui_b}`)

### 14.2 Tier 2 — All Other Drug Features: SerpAPI Web Search

**Activated when:** Drug RAG returns insufficient results for any drug feature other than drug-drug interaction.

**Search query construction per feature:**

| Feature | Search Query Template |
|---|---|
| Drug profile | `"{drug_name}" uses side effects dosage site:drugs.com OR site:medlineplus.gov` |
| Drug-food interaction | `"{drug_name}" food interactions dietary restrictions site:drugs.com` |
| Drug-disease contraindication | `"{drug_name}" contraindicated "{disease}" site:drugs.com OR site:fda.gov` |
| Pregnancy safety | `"{drug_name}" pregnancy safety FDA category breastfeeding site:drugs.com` |
| Dosage calculator | `"{drug_name}" dosage adults pediatric renal adjustment site:drugs.com` |
| Drug alternatives | `alternatives to "{drug_name}" same class site:drugs.com OR site:medlineplus.gov` |
| Drug comparison | `"{drug_a}" vs "{drug_b}" comparison efficacy site:drugs.com` |
| Pharmacokinetics | `"{drug_name}" pharmacokinetics half-life CYP metabolism site:drugs.com` |
| Off-label uses | `"{drug_name}" off-label uses evidence site:drugs.com` |

**Agent flow:**
1. Construct appropriate search query for the feature
2. Call SerpAPI with the query
3. Extract result snippets from top 3 results
4. Pass snippet text + source URLs to medical LLM for response generation
5. Label response with source URLs as citations

### 14.3 Tier 2 — Medical RAG Fallback: Web Search

Activated when Medical RAG returns insufficient results for chatbot queries about health topics, diseases, or symptoms.

**Search queries:** Topic-specific queries targeting medlineplus.gov, mayoclinic.org, and who.int as preferred sources.

### 14.4 Caching — All Tiers

**Tier 0 — DDIMDL structured lookup results:**

| Cache Key | TTL | Contents |
|---|---|---|
| `ddimdl_lookup:{drugbank_id_a}:{drugbank_id_b}` | 12 hours | Full interaction text + mechanism type |
| `ddimdl_name_to_id:{name_hash}` | 24 hours | DrugBank ID for a given drug name |
| `ddimdl_features:{drugbank_id}` | 24 hours | Molecular features object (targets, enzymes, cyp_enzymes, smile) |
| `ddimdl_name_index` | Permanent (loaded at startup) | Redis hash of all 572 drug names → DrugBank IDs |

**Tier 2 — Drugs.com web results:**

| Cache Key | TTL | Contents |
|---|---|---|
| `web_interaction:{rxcui_a}:{rxcui_b}` | 6 hours | Live Drugs.com interaction result |
| `web_drug_profile:{rxcui}` | 12 hours | Web-sourced drug profile |
| `web_pregnancy:{rxcui}` | 24 hours | Web-sourced pregnancy safety |
| `web_medical:{topic_hash}` | 6 hours | Web-sourced medical topic answer |

---

## 15. Scraping and Ingestion Run Order

This section defines the correct order to run all data collection and ingestion operations to build the complete MAISYS knowledge bases from scratch.

### Phase 1 — Drugs.com Scraping (already partially complete)

1. Run `drugs_general_scraper.py` — general drug pages → `drugs_general_output/` ✅ Complete
2. Run `scraper_professional.py` — professional pages → `drugs_professional_output/` 🔄 Continue
3. After professional scraper completes: run `retry_failed_drugs.py` — recover failed URLs

### Phase 2 — MedlinePlus Scraping

Run all 5 parts sequentially (to respect rate limits — 3–8 second delays):
1. `medlineplus/part1_health_topics/scraper.py`
2. `medlineplus/part2_drugs/scraper.py`
3. `medlineplus/part3_lab_tests/scraper.py`
4. `medlineplus/part4_encyclopedia/scraper.py`
5. `medlineplus/part5_genetics/scraper.py`

Each scraper resumes automatically if interrupted. Run them one at a time.

### Phase 3 — Mayo Clinic Scraping

Run all 4 parts sequentially:
1. `mayo_clinic/part1_diseases_conditions/scraper.py`
2. `mayo_clinic/part2_symptoms/scraper.py`
3. `mayo_clinic/part3_tests_procedures/scraper.py`
4. `mayo_clinic/part4_drugs/scraper.py`

### Phase 3.5 — DDIMDL Processing (no scraping needed — files already in hand)

**Input files required:**
- `drug_data.csv` — 572 drugs with molecular features (targets, enzymes, pathways, SMILES)
- `Interactions.csv` — 37,264 drug-drug interaction descriptions from DrugBank 5.1.3

**Run:**
```
cd services/drug-service
python ingestion/ingest_ddimdl.py \
  --drug-data /path/to/drug_data.csv \
  --interactions /path/to/Interactions.csv
```

**What the script does (in order):**
1. Parses `drug_data.csv` — splits pipe-separated target/enzyme/pathway fields into arrays, maps enzyme UniProt IDs to CYP enzyme names, bulk inserts 572 rows into `ddimdl_drug_features`
2. Attempts RxNorm resolution for all 572 drug names — updates `rxcui` and `canonical_name` fields
3. Parses `Interactions.csv` — classifies mechanism type per row by keyword detection, normalizes pair directionality (lexicographic ordering), bulk inserts 37,264 rows into `ddimdl_interactions`
4. Attempts RxNorm resolution for all drug names in interactions — updates `rxcui_a` and `rxcui_b`
5. Pre-loads name→DrugBank ID index into Redis hash `ddimdl_name_index` (572 entries — negligible memory)
6. Embeds all 37,264 interaction chunks with MiniLM-L6-v2 → upserts to `drug_minilm` Qdrant collection
7. Embeds all 37,264 interaction chunks with PubMedBERT → upserts to `drug_pubmedbert` Qdrant collection
8. Prints ingestion summary: records inserted, RxNorm resolution rate, Qdrant chunks upserted, errors

**Verify after completion:**
- `SELECT COUNT(*) FROM ddimdl_interactions` → expect 37,264
- `SELECT COUNT(*) FROM ddimdl_drug_features` → expect 572
- `SELECT COUNT(*) FROM ddimdl_drug_features WHERE rxcui IS NOT NULL` → expect > 90% resolved
- Qdrant chunk count for `drug_minilm` increased by ~37,264
- Test Tier 0 lookup: query known pair (Abemaciclib + Amiodarone) → result returned in < 100ms

**Expected runtime:** 20–45 minutes (dominated by RxNorm API calls — rate limited to 0.5s per call)

**Citation stored with every DDIMDL record:** Deng Y, Xu X, Qiu Y, Xia J, Zhang W, Liu S. "A multimodal deep learning framework for predicting drug-drug interaction events." *Bioinformatics*, 2020. Data: DrugBank 5.1.3.

### Phase 4 — Drug RAG Ingestion

After Phases 1–3 produce all source data:
```
cd services/drug-service
python ingestion/run_drug_ingestion.py
```
This runs all 4 drug ingestion steps in order and reports progress and errors.

Verify ingestion: check Qdrant `drug_minilm` and `drug_pubmedbert` collections contain expected vector counts. Run test queries for 5 common drugs and verify results are returned.

### Phase 5 — Medical RAG Ingestion

```
cd services/chatbot-service
python ingestion/run_all_ingestion.py
```
Runs all 7 Medical RAG ingestion steps in order.

Verify: check `medical_minilm` and `medical_pubmedbert` collections. Test queries for common conditions, lab tests, and health topics.

### Phase 6 — Infermedica and EndlessMedical Scraping (Beta training data)

Run separately — not required for main platform operation:
1. `infermedica_scraper.py` — requires APP_ID and APP_KEY, runs ~2–4 hours
2. `endlessmedical_scraper.py` — no credentials, runs ~1–2 hours

### Phase 7 — Beta Training Pipeline (after Phases 6 complete)

1. Run `download_medical_datasets.py` — downloads HuggingFace datasets
2. Run `infermedica_to_beta_training.py` — converts Infermedica + EndlessMedical data to JSONL
3. Run normalizers for each additional dataset (MIMIC-III, PrimeKG, MIT KG, Mendeley, Kaggle)
4. Run `merge_and_split.py` — merges all JSONL files, shuffles, splits 80/10/10
5. Run `quality_checker.py` — validates class balance, triage distribution, minimum record count

Paper RAG collections are created on demand as users add papers to research sessions — no pre-ingestion needed.

---

*MAISYS Technical Guide — Part 2: Data Collection · Extraction · Chunking · RAG Knowledge Base*
