# MAISYS — Technical Development Guide
## Part 5: Database Schemas · API Contracts · Safety Service · Auth Service · Notification Service · Frontend Detail · Environment Variables

---

## Table of Contents

1. [Database Schemas — All 14 Services](#1-database-schemas--all-14-services)
2. [Alembic Migration Structure](#2-alembic-migration-structure)
3. [API Contracts — Complete Request/Response Shapes](#3-api-contracts--complete-requestresponse-shapes)
4. [WebSocket and Streaming Event Contracts](#4-websocket-and-streaming-event-contracts)
5. [Safety Service — Complete Specification](#5-safety-service--complete-specification)
6. [Auth Service — Complete Specification](#6-auth-service--complete-specification)
7. [Notification Service — Complete Specification](#7-notification-service--complete-specification)
8. [Frontend — Component Trees and State Per Page](#8-frontend--component-trees-and-state-per-page)
9. [Environment Variables — Complete Reference](#9-environment-variables--complete-reference)

---

## 1. Database Schemas — All 14 Services

Column type notation: `UUID`, `VARCHAR(n)`, `TEXT`, `INTEGER`, `BIGINT`, `BOOLEAN`, `TIMESTAMP WITH TIME ZONE` (abbreviated as `TIMESTAMPTZ`), `JSONB`, `FLOAT`, `SMALLINT`.
All `id` columns are UUID type unless stated otherwise.
All tables include `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` unless stated otherwise.
`PK` = Primary Key, `FK` = Foreign Key, `NN` = NOT NULL, `UQ` = UNIQUE, `IDX` = Index.

---

### 1.1 auth-service — `maisys_auth_db`

**Table: `users`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `email` | VARCHAR(255) | NN, UQ | Stored lowercase |
| `email_hash` | VARCHAR(64) | NN, UQ, IDX | SHA-256 of email — used for fast lookup |
| `password_hash` | VARCHAR(255) | NULL | Null for pure-OAuth accounts |
| `role` | VARCHAR(20) | NN, DEFAULT 'user' | user / beta_user / gp_reviewer / admin |
| `email_verified` | BOOLEAN | NN, DEFAULT false | |
| `is_active` | BOOLEAN | NN, DEFAULT true | False = deactivated account |
| `language_preference` | VARCHAR(5) | NN, DEFAULT 'en' | en / ar |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | Updated by trigger |
| `last_login_at` | TIMESTAMPTZ | NULL | |
| `deleted_at` | TIMESTAMPTZ | NULL | Soft delete timestamp |

Indexes: `idx_users_email_hash`, `idx_users_role`, `idx_users_created_at`

---

**Table: `refresh_tokens`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, FK users(id) ON DELETE CASCADE | |
| `token_hash` | VARCHAR(64) | NN, UQ, IDX | SHA-256 of the raw token |
| `expires_at` | TIMESTAMPTZ | NN | 7 days from issuance |
| `revoked` | BOOLEAN | NN, DEFAULT false | |
| `revoked_at` | TIMESTAMPTZ | NULL | |
| `user_agent` | VARCHAR(512) | NULL | Browser/client identification |
| `ip_address` | VARCHAR(45) | NULL | IPv4 or IPv6 |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_refresh_tokens_user_id`, `idx_refresh_tokens_token_hash`

---

**Table: `otp_codes`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, FK users(id) ON DELETE CASCADE | |
| `code_hash` | VARCHAR(64) | NN | SHA-256 of 6-digit code |
| `purpose` | VARCHAR(30) | NN | email_verify / password_reset / login_otp |
| `expires_at` | TIMESTAMPTZ | NN | 10 minutes from creation |
| `used` | BOOLEAN | NN, DEFAULT false | |
| `used_at` | TIMESTAMPTZ | NULL | |
| `attempt_count` | SMALLINT | NN, DEFAULT 0 | Max 5 attempts before invalidation |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_otp_user_purpose` (user_id, purpose, used, expires_at)

---

**Table: `oauth_accounts`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, FK users(id) ON DELETE CASCADE | |
| `provider` | VARCHAR(20) | NN | google / apple |
| `provider_user_id` | VARCHAR(255) | NN | Provider's user ID |
| `provider_email` | VARCHAR(255) | NULL | Email from provider |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Unique constraint: `(provider, provider_user_id)`
Indexes: `idx_oauth_user_id`, `idx_oauth_provider_user`

---

**Table: `sessions`** (JWT tracking for revocation)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN | |
| `user_id` | UUID | NN, FK users(id) ON DELETE CASCADE | |
| `jwt_jti` | VARCHAR(36) | NN, UQ, IDX | JWT ID claim — unique per token |
| `issued_at` | TIMESTAMPTZ | NN | |
| `expires_at` | TIMESTAMPTZ | NN | |
| `revoked` | BOOLEAN | NN, DEFAULT false | |
| `revoked_at` | TIMESTAMPTZ | NULL | |

Indexes: `idx_sessions_user_id`, `idx_sessions_jwt_jti`, `idx_sessions_expires_at`

---

### 1.2 chatbot-service — `maisys_chatbot_db`

**Table: `chat_sessions`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, IDX | FK to auth-service users (cross-service — no DB FK) |
| `title` | VARCHAR(255) | NN, DEFAULT 'New Conversation' | |
| `share_token` | VARCHAR(64) | NULL, UQ | Generated on share request |
| `share_expires_at` | TIMESTAMPTZ | NULL | |
| `conversation_summary` | TEXT | NULL | Rolling summary of older messages |
| `last_summarized_at` | TIMESTAMPTZ | NULL | |
| `total_message_count` | INTEGER | NN, DEFAULT 0 | |
| `is_archived` | BOOLEAN | NN, DEFAULT false | |
| `is_starred` | BOOLEAN | NN, DEFAULT false | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_chat_sessions_user_id`, `idx_chat_sessions_share_token`, `idx_chat_sessions_updated_at`

---

**Table: `chat_messages`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK chat_sessions(id) ON DELETE CASCADE | |
| `role` | VARCHAR(10) | NN | user / assistant |
| `content` | TEXT | NN | Full message text |
| `citations` | JSONB | NULL | Array of citation objects |
| `input_type` | VARCHAR(10) | NN, DEFAULT 'text' | text / voice / image / file |
| `feedback` | VARCHAR(10) | NULL | like / dislike |
| `visual_id` | UUID | NULL, FK chat_visuals(id) | If a visual was generated for this message |
| `source_tier` | VARCHAR(10) | NULL | local / web |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_chat_messages_session_id`, `idx_chat_messages_created_at`

Citations JSONB schema:
```json
[{"source": "Drugs.com Professional", "title": "Ibuprofen Prescribing Info", "url": "...", "section": "PHARMACOKINETICS"}]
```

---

**Table: `user_health_profiles`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, UQ, IDX | One profile per user |
| `age` | SMALLINT | NULL | |
| `gender` | VARCHAR(10) | NULL | male / female / other / prefer_not |
| `blood_type` | VARCHAR(5) | NULL | A+ / A- / B+ / B- / AB+ / AB- / O+ / O- |
| `is_pregnant` | BOOLEAN | NULL | NULL = unknown |
| `has_diabetes` | BOOLEAN | NULL | |
| `has_hypertension` | BOOLEAN | NULL | |
| `has_heart_disease` | BOOLEAN | NULL | |
| `has_kidney_disease` | BOOLEAN | NULL | |
| `chronic_conditions` | JSONB | NULL | Array of condition name strings |
| `current_medications` | JSONB | NULL | Array of medication name strings |
| `allergies` | JSONB | NULL | Array of allergy strings |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `chat_visuals`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK chat_sessions(id) ON DELETE CASCADE | |
| `message_id` | UUID | NULL, FK chat_messages(id) | |
| `visual_type` | VARCHAR(15) | NN | chart / infographic / diagram |
| `chart_subtype` | VARCHAR(10) | NULL | bar / line / radar (for chart type) |
| `diagram_subtype` | VARCHAR(20) | NULL | mechanism / timeline / body / flowchart |
| `title` | VARCHAR(255) | NULL | |
| `html_content` | TEXT | NN | Full self-contained HTML |
| `png_path` | VARCHAR(512) | NULL | Object storage path to rendered PNG |
| `chart_llm_used` | VARCHAR(100) | NULL | Model that generated the visual |
| `generation_duration_ms` | INTEGER | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `uploaded_files`** (chatbot-service)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK chat_sessions(id) ON DELETE CASCADE | |
| `message_id` | UUID | NULL, FK chat_messages(id) | |
| `original_filename` | VARCHAR(512) | NN | |
| `safe_filename` | VARCHAR(512) | NN | Sanitized filename |
| `file_path` | VARCHAR(1024) | NN | Object storage path |
| `file_type` | VARCHAR(10) | NN | pdf / docx / image |
| `mime_type` | VARCHAR(100) | NN | |
| `size_bytes` | BIGINT | NN | |
| `qdrant_indexed` | BOOLEAN | NN, DEFAULT false | Whether file is in session Qdrant namespace |
| `qdrant_namespace` | VARCHAR(100) | NULL | Qdrant collection name for this file |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `agent_trace_log`** (chatbot-service — same structure in drug, lab, research services)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `trace_id` | UUID | NN, IDX | One trace per agent execution |
| `session_id` | UUID | NN, IDX | |
| `agent_name` | VARCHAR(100) | NN | e.g. InteractionAgent |
| `graph_name` | VARCHAR(100) | NN | e.g. drug_interaction |
| `node_name` | VARCHAR(100) | NN | e.g. rag_retrieval |
| `event_type` | VARCHAR(20) | NN | agent_start / node_start / node_complete / node_error / node_skipped / tool_call / tool_result / agent_complete |
| `duration_ms` | INTEGER | NULL | For complete/error events |
| `tokens_used` | INTEGER | NULL | LLM nodes only |
| `input_summary` | VARCHAR(500) | NULL | First 500 chars of input |
| `output_summary` | VARCHAR(500) | NULL | First 500 chars of output |
| `error_type` | VARCHAR(100) | NULL | Exception class name |
| `error_message` | VARCHAR(1000) | NULL | |
| `will_retry` | BOOLEAN | NULL | For error events |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_agent_trace_trace_id`, `idx_agent_trace_session_id`, `idx_agent_trace_created_at`
Retention: 30 days (scheduled purge job removes records older than 30 days)

---

### 1.3 drug-service — `maisys_drug_db`

**Table: `drug_sessions`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, IDX | Cross-service reference |
| `feature` | VARCHAR(30) | NN | profile / brand_generic / class_browser / drug_drug / drug_food / drug_disease / pregnancy / dosage / alternatives / comparison / pharmacokinetics / off_label |
| `input_drugs` | JSONB | NN | Array of normalized drug objects |
| `result` | JSONB | NULL | Full structured result |
| `source_tier` | VARCHAR(15) | NULL | local / web / structured |
| `web_sources` | JSONB | NULL | Array of {name, url} objects |
| `total_tokens_used` | INTEGER | NULL | |
| `agent_trace_id` | UUID | NULL, IDX | Links to agent_trace_log |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Input drugs JSONB schema:
```json
[{"original_name": "Tylenol", "canonical_name": "acetaminophen", "rxcui": "161", "active_ingredients": ["161"], "duplicate_flag": false}]
```

---

**Table: `drug_export_history`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN | |
| `session_id` | UUID | NN, FK drug_sessions(id) | |
| `user_id` | UUID | NN, IDX | |
| `format` | VARCHAR(5) | NN | txt / docx / pdf |
| `export_job_id` | UUID | NULL | Reference to export-service job |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `model_usage_log`** (drug-service)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN | |
| `session_id` | UUID | NULL, IDX | |
| `feature` | VARCHAR(30) | NULL | |
| `model_name` | VARCHAR(100) | NN | |
| `provider` | VARCHAR(30) | NN | |
| `role` | VARCHAR(20) | NN | medical / chart / embedding |
| `input_tokens` | INTEGER | NULL | |
| `output_tokens` | INTEGER | NULL | |
| `duration_ms` | INTEGER | NULL | |
| `cache_hit` | BOOLEAN | NN, DEFAULT false | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_model_usage_session_id`, `idx_model_usage_created_at`

---

**Table: `ddimdl_interactions`**

Stores all 37,264 drug-drug interaction records from DrugBank 5.1.3 (DDIMDL dataset, Deng et al., Bioinformatics, 2020). Used as Tier 0 exact-match lookup before RAG search — returns results in sub-100ms for known pairs.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `drugbank_id_a` | VARCHAR(10) | NN, IDX | Lexicographically smaller DrugBank ID of the pair |
| `name_a` | VARCHAR(255) | NN | |
| `drugbank_id_b` | VARCHAR(10) | NN, IDX | |
| `name_b` | VARCHAR(255) | NN | |
| `interaction_text` | TEXT | NN | Full natural language description from DrugBank 5.1.3 |
| `mechanism_type` | VARCHAR(30) | NN, IDX | serum_concentration / metabolism / risk_adverse / therapeutic_efficacy / anticoagulant / hypoglycemic / neuromuscular / other |
| `rxcui_a` | VARCHAR(20) | NULL, IDX | Populated after RxNorm resolution |
| `rxcui_b` | VARCHAR(20) | NULL | |
| `qdrant_chunk_id` | VARCHAR(100) | NULL | Reference to corresponding chunk in Drug RAG Qdrant |

Unique constraint: `(drugbank_id_a, drugbank_id_b)` — directionality normalized (always lexicographically smaller ID as `drugbank_id_a`).

Indexes:
- `idx_ddimdl_pair` on `(drugbank_id_a, drugbank_id_b)` — primary lookup
- `idx_ddimdl_pair_reverse` on `(drugbank_id_b, drugbank_id_a)` — reverse pair lookup
- `idx_ddimdl_name_a` on `name_a`
- `idx_ddimdl_name_b` on `name_b`
- `idx_ddimdl_rxcui_pair` on `(rxcui_a, rxcui_b)` — RxNorm-based lookup
- `idx_ddimdl_mechanism` on `mechanism_type`

---

**Table: `ddimdl_drug_features`**

Stores molecular feature data for 572 drugs from DrugBank 5.1.3. Used to enrich Pharmacokinetics Viewer (CYP enzyme mapping) and Drug Comparison (shared targets, SMILES similarity).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `drugbank_id` | VARCHAR(10) | NN, UQ, IDX | e.g. DB01296 |
| `name` | VARCHAR(255) | NN, IDX | |
| `rxcui` | VARCHAR(20) | NULL, IDX | Populated after RxNorm resolution |
| `canonical_name` | VARCHAR(255) | NULL | RxNorm canonical name |
| `targets` | JSONB | NN | Array of UniProt protein target ID strings |
| `enzymes` | JSONB | NN | Array of UniProt enzyme ID strings |
| `cyp_enzymes` | JSONB | NULL | Array of CYP enzyme names derived from enzymes field — e.g. ["CYP3A4", "CYP2D6"] |
| `pathways` | JSONB | NN | Array of KEGG pathway ID strings |
| `smile` | TEXT | NN | SMILES chemical structure string |
| `rxnorm_resolved` | BOOLEAN | NN, DEFAULT false | Whether RxNorm resolution was attempted and succeeded |

**CYP enzyme mapping used during ingestion:**

| UniProt ID | CYP Enzyme |
|---|---|
| P08684 | CYP3A4 |
| P10635 | CYP2D6 |
| P11712 | CYP2C9 |
| P05177 | CYP1A2 |
| P33261 | CYP2C19 |
| P10632 | CYP2C8 |
| Q06520 | CYP2A6 |

---

### 1.4 symptom-service — `maisys_symptom_db`

**Table: `symptom_sessions`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN | This IS the Infermedica Interview-Id |
| `user_id` | UUID | NN, IDX | |
| `mode` | VARCHAR(10) | NN | alpha / beta |
| `age` | SMALLINT | NN | |
| `sex` | VARCHAR(6) | NN | male / female |
| `language` | VARCHAR(5) | NN | en / ar |
| `chief_complaint` | TEXT | NN | Original user text |
| `chief_complaint_translated` | TEXT | NULL | English translation (if input was Arabic) |
| `evidence` | JSONB | NN, DEFAULT '[]' | Current evidence array |
| `turns` | SMALLINT | NN, DEFAULT 0 | |
| `status` | VARCHAR(15) | NN, DEFAULT 'active' | active / complete / abandoned / error |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `completed_at` | TIMESTAMPTZ | NULL | |

Indexes: `idx_symptom_sessions_user_id`, `idx_symptom_sessions_status`

Evidence JSONB: `[{"id": "s_1193", "choice_id": "present"}, ...]`

---

**Table: `symptom_results`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, UQ, FK symptom_sessions(id) | One result per session |
| `conditions` | JSONB | NN | Array of {id, name, probability} |
| `condition_details` | JSONB | NULL | Full Infermedica condition detail objects |
| `triage_level` | VARCHAR(25) | NN | emergency / emergency_ambulance / consultation_24 / consultation / self_care |
| `triage_color` | VARCHAR(10) | NN | red / orange / yellow / green |
| `triage_action` | TEXT | NN | User-facing action string |
| `explanation` | TEXT | NN | LLM-generated plain language explanation |
| `triage_summary` | TEXT | NN | LLM-generated triage guidance |
| `background_info` | TEXT | NULL | RAG-retrieved background on top condition |
| `background_sources` | JSONB | NULL | Array of source citation objects |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `symptom_export_history`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN | |
| `session_id` | UUID | NN, FK symptom_sessions(id) | |
| `user_id` | UUID | NN, IDX | |
| `format` | VARCHAR(5) | NN | txt / docx / pdf |
| `export_job_id` | UUID | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `beta_consents`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `user_id` | UUID | PK, NN | One row per user |
| `gate_1_consent` | BOOLEAN | NN, DEFAULT false | Explicit consent screen |
| `gate_1_timestamp` | TIMESTAMPTZ | NULL | |
| `gate_1_consent_version` | VARCHAR(10) | NULL | Version of consent text shown |
| `gate_2_consent` | BOOLEAN | NN, DEFAULT false | Account settings toggle |
| `gate_2_timestamp` | TIMESTAMPTZ | NULL | |
| `gate_3_consent` | BOOLEAN | NN, DEFAULT false | Onboarding flow |
| `gate_3_timestamp` | TIMESTAMPTZ | NULL | |
| `withdrawn` | BOOLEAN | NN, DEFAULT false | |
| `withdrawn_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `beta_sessions`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id_hash` | VARCHAR(64) | NN, IDX | SHA-256 of original user_id |
| `age` | SMALLINT | NULL | Kept — not PII |
| `sex` | VARCHAR(6) | NULL | |
| `chief_complaint` | TEXT | NN | Already anonymized (PII removed) |
| `turns` | SMALLINT | NN | |
| `beta_response` | TEXT | NN | Fine-tuned model response |
| `beta_triage_estimate` | VARCHAR(25) | NULL | Model's triage estimate |
| `consent_version` | VARCHAR(10) | NN | Which consent version was active |
| `date_offset_days` | SMALLINT | NN | Random ±30 offset applied |
| `review_queue_id` | UUID | NULL, FK beta_review_queue(id) | |
| `created_at` | TIMESTAMPTZ | NN | Date already shifted by date_offset_days |

---

**Table: `beta_review_queue`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `source_type` | VARCHAR(30) | NN | beta_session / infermedica / endlessmedical / mimic / primekg / mendeley / kaggle / etc. |
| `unified_record` | JSONB | NN | Complete unified schema record |
| `gp_reviewed` | BOOLEAN | NN, DEFAULT false | |
| `gp_reviewer_id` | UUID | NULL | Admin user ID of GP reviewer |
| `gp_action` | VARCHAR(20) | NULL | approve / correct_approve / reject / flag |
| `gp_corrected_diagnosis` | VARCHAR(500) | NULL | GP's corrected primary diagnosis |
| `gp_corrected_triage` | VARCHAR(25) | NULL | GP's corrected triage level |
| `gp_notes` | TEXT | NULL | Reviewer notes |
| `approved_for_training` | BOOLEAN | NN, DEFAULT false | |
| `withdrawn` | BOOLEAN | NN, DEFAULT false | Set true if user withdraws consent |
| `reviewed_at` | TIMESTAMPTZ | NULL | |
| `flagged_for_discussion` | BOOLEAN | NN, DEFAULT false | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_beta_review_gp_reviewed`, `idx_beta_review_approved`, `idx_beta_review_source_type`

---

**Table: `beta_training_runs`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `base_model` | VARCHAR(100) | NN | HuggingFace model ID |
| `dataset_size_train` | INTEGER | NN | |
| `dataset_size_val` | INTEGER | NN | |
| `dataset_size_test` | INTEGER | NN | |
| `triage_accuracy` | FLOAT | NULL | 0.0–1.0 |
| `top_condition_accuracy` | FLOAT | NULL | |
| `emergency_false_negative_rate` | FLOAT | NULL | Must be 0.0 to deploy |
| `lora_r` | SMALLINT | NULL | |
| `lora_alpha` | SMALLINT | NULL | |
| `num_epochs` | SMALLINT | NULL | |
| `adapter_path` | VARCHAR(512) | NULL | Object storage path |
| `deployed` | BOOLEAN | NN, DEFAULT false | |
| `deployed_at` | TIMESTAMPTZ | NULL | |
| `deployment_notes` | TEXT | NULL | |
| `run_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

### 1.5 lab-service — `maisys_lab_db`

**Table: `lab_sessions`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, IDX | |
| `original_filename` | VARCHAR(512) | NN | |
| `safe_filename` | VARCHAR(512) | NN | |
| `file_path` | VARCHAR(1024) | NN | Object storage path |
| `file_type` | VARCHAR(10) | NN | pdf / jpg / png / webp / docx |
| `processing_path` | VARCHAR(5) | NULL | A / B / C / D |
| `status` | VARCHAR(15) | NN, DEFAULT 'processing' | processing / complete / error |
| `error_message` | VARCHAR(1000) | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `completed_at` | TIMESTAMPTZ | NULL | |

---

**Table: `lab_tests`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK lab_sessions(id) ON DELETE CASCADE | |
| `test_name` | VARCHAR(255) | NN | As extracted from report |
| `normalized_name` | VARCHAR(255) | NULL | Matched to standard test name |
| `value` | VARCHAR(50) | NN | Raw value string |
| `value_numeric` | FLOAT | NULL | Parsed numeric value if applicable |
| `unit` | VARCHAR(50) | NULL | |
| `reference_range` | VARCHAR(100) | NULL | "12.0-16.0" or "<5.0" etc. |
| `ref_range_low` | FLOAT | NULL | Parsed lower bound |
| `ref_range_high` | FLOAT | NULL | Parsed upper bound |
| `status` | VARCHAR(10) | NN | normal / high / low / critical / unknown |
| `flag` | VARCHAR(10) | NULL | H / L / HH / LL / CRITICAL / NORMAL |
| `section` | VARCHAR(100) | NULL | Panel name e.g. CBC / Metabolic Panel |
| `sort_order` | INTEGER | NN, DEFAULT 0 | Preserves report order |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_lab_tests_session_id`, `idx_lab_tests_status`

---

**Table: `lab_explanations`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `lab_test_id` | UUID | NN, UQ, FK lab_tests(id) ON DELETE CASCADE | One per test |
| `what_it_measures` | TEXT | NN | |
| `what_result_means` | TEXT | NN | Contextualized to actual value |
| `possible_causes` | TEXT | NULL | For abnormal results |
| `affecting_factors` | TEXT | NULL | Medications, diet, etc. |
| `urgency_level` | VARCHAR(10) | NN | none / monitor / discuss / urgent |
| `rag_sources` | JSONB | NULL | Sources used for enrichment |
| `llm_model_used` | VARCHAR(100) | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `lab_summaries`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, UQ, FK lab_sessions(id) ON DELETE CASCADE | |
| `summary_text` | TEXT | NN | |
| `urgency_level` | VARCHAR(10) | NN | none / routine / soon / urgent |
| `total_tests` | SMALLINT | NN | |
| `normal_count` | SMALLINT | NN | |
| `high_count` | SMALLINT | NN | |
| `low_count` | SMALLINT | NN | |
| `critical_count` | SMALLINT | NN | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `lab_visuals`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK lab_sessions(id) ON DELETE CASCADE | |
| `visual_type` | VARCHAR(15) | NN | chart / infographic / diagram |
| `html_content` | TEXT | NN | |
| `png_path` | VARCHAR(512) | NULL | |
| `trigger_reason` | VARCHAR(100) | NULL | Why this visual was generated |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `lab_chat_messages`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK lab_sessions(id) ON DELETE CASCADE | |
| `role` | VARCHAR(10) | NN | user / assistant |
| `content` | TEXT | NN | |
| `citations` | JSONB | NULL | |
| `input_type` | VARCHAR(10) | NN, DEFAULT 'text' | text / voice / image |
| `feedback` | VARCHAR(10) | NULL | like / dislike |
| `visual_id` | UUID | NULL, FK lab_visuals(id) | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

### 1.6 research-service — `maisys_research_db`

**Table: `research_sessions`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, IDX | |
| `title` | VARCHAR(255) | NN, DEFAULT 'New Research Session' | |
| `share_token` | VARCHAR(64) | NULL, UQ | |
| `share_expires_at` | TIMESTAMPTZ | NULL | |
| `paper_count` | SMALLINT | NN, DEFAULT 0 | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `papers`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK research_sessions(id) ON DELETE CASCADE | |
| `title` | VARCHAR(1000) | NN | |
| `authors` | JSONB | NULL | Array of author name strings |
| `doi` | VARCHAR(255) | NULL, IDX | |
| `year` | SMALLINT | NULL | |
| `abstract` | TEXT | NULL | |
| `journal` | VARCHAR(500) | NULL | |
| `file_path` | VARCHAR(1024) | NULL | Object storage path |
| `source` | VARCHAR(20) | NN | upload / semantic_scholar / pending_upload |
| `source_url` | VARCHAR(2048) | NULL | Publisher/download URL |
| `researchgate_url` | VARCHAR(2048) | NULL | |
| `qdrant_collection_minilm` | VARCHAR(100) | NULL | papers_{session_id}_minilm |
| `qdrant_collection_pubmedbert` | VARCHAR(100) | NULL | |
| `chunk_count` | INTEGER | NULL | Total chunks indexed |
| `extraction_method` | VARCHAR(20) | NULL | pymupdf / ocr / vision / docx |
| `status` | VARCHAR(20) | NN, DEFAULT 'processing' | processing / indexed / awaiting_file / error |
| `error_message` | VARCHAR(1000) | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `paper_chat_messages`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK research_sessions(id) ON DELETE CASCADE | |
| `paper_ids` | JSONB | NULL | Array of paper UUIDs this message relates to |
| `role` | VARCHAR(10) | NN | user / assistant |
| `content` | TEXT | NN | |
| `citations` | JSONB | NULL | Array of {paper_title, authors, year, section, page_range, doi} |
| `input_type` | VARCHAR(10) | NN, DEFAULT 'text' | text / voice / image |
| `feedback` | VARCHAR(10) | NULL | like / dislike |
| `visual_id` | UUID | NULL | |
| `conversation_summary` | TEXT | NULL | Rolling summary (same sliding window as chatbot) |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `paper_summaries`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `paper_id` | UUID | NN, IDX, FK papers(id) ON DELETE CASCADE | |
| `summary_type` | VARCHAR(20) | NN | brief / structured / key_points |
| `mode_used` | VARCHAR(10) | NN | model / llm |
| `model_name` | VARCHAR(100) | NULL | |
| `content` | TEXT | NN | |
| `language` | VARCHAR(5) | NN | en / ar |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Unique constraint: `(paper_id, summary_type, language)`

---

**Table: `paper_translations`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `paper_id` | UUID | NN, IDX, FK papers(id) ON DELETE CASCADE | |
| `source_language` | VARCHAR(5) | NN | en / ar |
| `target_language` | VARCHAR(5) | NN | en / ar |
| `scope` | VARCHAR(20) | NN | abstract / full / section |
| `section_name` | VARCHAR(100) | NULL | If scope = section |
| `mode_used` | VARCHAR(10) | NN | model / llm |
| `model_name` | VARCHAR(100) | NULL | |
| `translated_content` | TEXT | NN | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Unique constraint: `(paper_id, source_language, target_language, scope, section_name)`

---

**Table: `paper_qa_sets`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `paper_id` | UUID | NN, IDX, FK papers(id) ON DELETE CASCADE | |
| `mode_used` | VARCHAR(10) | NN | model / llm |
| `model_name` | VARCHAR(100) | NULL | |
| `qa_pairs` | JSONB | NN | Array of {question, answer, difficulty, section} |
| `qa_count` | SMALLINT | NN | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

qa_pairs JSONB: `[{"question": "...", "answer": "...", "difficulty": "comprehension", "section": "Results"}]`

---

**Table: `paper_comparisons`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK research_sessions(id) ON DELETE CASCADE | |
| `paper_ids` | JSONB | NN | Array of paper UUIDs compared |
| `comparison_table` | JSONB | NN | Rows of {attribute, paper_1_value, paper_2_value, ...} |
| `narrative` | TEXT | NN | LLM synthesis narrative |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `discovery_jobs`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `session_id` | UUID | NN, IDX, FK research_sessions(id) ON DELETE CASCADE | |
| `query` | TEXT | NN | User's original description |
| `extracted_keywords` | JSONB | NULL | Keywords extracted by LLM |
| `status` | VARCHAR(15) | NN, DEFAULT 'queued' | queued / running / complete / error |
| `total_found` | SMALLINT | NULL | |
| `successfully_added` | SMALLINT | NULL | |
| `pending_upload_count` | SMALLINT | NULL | |
| `results` | JSONB | NULL | Full discovery report |
| `error_message` | VARCHAR(1000) | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `completed_at` | TIMESTAMPTZ | NULL | |

---

### 1.7 export-service — `maisys_export_db`

**Table: `export_jobs`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `source_service` | VARCHAR(30) | NN | chatbot / drug / symptom / lab / research |
| `source_session_id` | UUID | NN | Session ID in the source service |
| `user_id` | UUID | NN, IDX | |
| `format` | VARCHAR(5) | NN | txt / docx / pdf |
| `language` | VARCHAR(5) | NN | en / ar |
| `status` | VARCHAR(15) | NN, DEFAULT 'queued' | queued / processing / complete / error |
| `error_message` | VARCHAR(1000) | NULL | |
| `rabbitmq_correlation_id` | VARCHAR(36) | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `completed_at` | TIMESTAMPTZ | NULL | |

---

**Table: `export_files`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `job_id` | UUID | NN, UQ, FK export_jobs(id) ON DELETE CASCADE | |
| `file_path` | VARCHAR(1024) | NN | Object storage path |
| `file_size_bytes` | BIGINT | NN | |
| `download_count` | INTEGER | NN, DEFAULT 0 | |
| `expires_at` | TIMESTAMPTZ | NN | 24 hours from creation |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

### 1.8 notification-service — `maisys_notification_db`

**Table: `notification_log`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `user_id` | UUID | NN, IDX | |
| `notification_type` | VARCHAR(30) | NN | email_verify / password_reset / login_otp / export_ready / beta_review_complete |
| `recipient_email` | VARCHAR(255) | NN | |
| `subject` | VARCHAR(500) | NULL | |
| `template_name` | VARCHAR(100) | NN | |
| `status` | VARCHAR(10) | NN | sent / failed / queued |
| `provider` | VARCHAR(20) | NULL | sendgrid / smtp |
| `provider_message_id` | VARCHAR(255) | NULL | |
| `attempt_count` | SMALLINT | NN, DEFAULT 1 | |
| `error_detail` | VARCHAR(1000) | NULL | |
| `sent_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_notification_log_user_id`, `idx_notification_log_type`

---

### 1.9 model-router-service — `maisys_model_router_db`

**Table: `model_registry`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `model_name` | VARCHAR(200) | NN | Human-readable name |
| `provider` | VARCHAR(30) | NN | openai / anthropic / gemini / groq / mistral / cohere / azure / vllm / ollama |
| `model_string` | VARCHAR(200) | NN | LiteLLM model string |
| `role` | VARCHAR(20) | NN | medical / chart / vision / stt / tts / embedding / ocr |
| `is_local` | BOOLEAN | NN, DEFAULT false | Runs on vLLM/Ollama |
| `huggingface_id` | VARCHAR(200) | NULL | For local models |
| `context_window_tokens` | INTEGER | NULL | |
| `cost_per_1k_input_tokens` | FLOAT | NULL | USD. Null for local (no API cost) |
| `cost_per_1k_output_tokens` | FLOAT | NULL | |
| `supports_prefix_cache` | BOOLEAN | NN, DEFAULT false | |
| `supports_vision` | BOOLEAN | NN, DEFAULT false | |
| `supports_streaming` | BOOLEAN | NN, DEFAULT true | |
| `latency_sla_ms` | INTEGER | NULL | Expected P95 latency |
| `is_available` | BOOLEAN | NN, DEFAULT true | Can be toggled off if deprecated |
| `notes` | TEXT | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Unique constraint: `(model_string, role)`

---

**Table: `active_model_config`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `service_name` | VARCHAR(30) | NN | chatbot / drug / symptom / lab / research / all |
| `llm_role` | VARCHAR(20) | NN | medical / chart / vision / stt / tts / ocr |
| `model_registry_id` | UUID | NN, FK model_registry(id) | |
| `switched_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |
| `switched_by` | UUID | NULL | Admin user ID |
| `switch_reason` | VARCHAR(500) | NULL | |

Unique constraint: `(service_name, llm_role)` — only one active model per service+role combo

---

**Table: `model_usage_metrics`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `service_name` | VARCHAR(30) | NN | |
| `model_registry_id` | UUID | NN, FK model_registry(id) | |
| `metric_hour` | TIMESTAMPTZ | NN | Truncated to hour |
| `request_count` | INTEGER | NN, DEFAULT 0 | |
| `success_count` | INTEGER | NN, DEFAULT 0 | |
| `error_count` | INTEGER | NN, DEFAULT 0 | |
| `avg_latency_ms` | FLOAT | NULL | |
| `p95_latency_ms` | FLOAT | NULL | |
| `total_input_tokens` | BIGINT | NN, DEFAULT 0 | |
| `total_output_tokens` | BIGINT | NN, DEFAULT 0 | |
| `estimated_cost_usd` | FLOAT | NULL | |
| `cache_hits` | INTEGER | NN, DEFAULT 0 | |

Unique constraint: `(service_name, model_registry_id, metric_hour)`

---

### 1.10 admin-service — `maisys_admin_db`

**Table: `admin_users`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `email` | VARCHAR(255) | NN, UQ | |
| `password_hash` | VARCHAR(255) | NN | |
| `role` | VARCHAR(20) | NN | gp_reviewer / system_admin |
| `totp_secret` | VARCHAR(255) | NULL | Encrypted TOTP secret for MFA |
| `totp_enabled` | BOOLEAN | NN, DEFAULT false | |
| `is_active` | BOOLEAN | NN, DEFAULT true | |
| `allowed_ip_ranges` | JSONB | NULL | Array of CIDR strings |
| `last_login_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

---

**Table: `audit_log`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, NN, DEFAULT gen_random_uuid() | |
| `admin_user_id` | UUID | NN, IDX, FK admin_users(id) | |
| `action` | VARCHAR(100) | NN | switch_model / approve_beta_record / reject_beta_record / change_user_role / deactivate_user / etc. |
| `target_resource_type` | VARCHAR(50) | NULL | model_config / beta_record / user / etc. |
| `target_resource_id` | VARCHAR(255) | NULL | |
| `before_state` | JSONB | NULL | Previous state if applicable |
| `after_state` | JSONB | NULL | New state |
| `ip_address` | VARCHAR(45) | NN | |
| `created_at` | TIMESTAMPTZ | NN, DEFAULT NOW() | |

Indexes: `idx_audit_log_admin_user_id`, `idx_audit_log_action`, `idx_audit_log_created_at`

---

## 2. Alembic Migration Structure

Each service has its own Alembic configuration within the service directory. Migrations are never shared between services.

### 2.1 Directory Layout Per Service

```
services/{service_name}/
├── alembic.ini               ← points to SERVICE_DATABASE_URL env var
├── alembic/
│   ├── env.py                ← imports service's SQLAlchemy Base and models
│   ├── script.py.mako        ← migration file template
│   └── versions/
│       ├── 0001_initial_schema.py      ← creates all tables
│       ├── 0002_add_indexes.py         ← adds all indexes
│       └── 0003_add_{feature}.py       ← future schema changes
└── models/
    └── domain.py             ← SQLAlchemy ORM models imported by alembic/env.py
```

### 2.2 alembic.ini Per Service

```ini
[alembic]
script_location = alembic
sqlalchemy.url = %(SERVICE_DATABASE_URL)s
```

The `SERVICE_DATABASE_URL` variable name is different per service: `CHATBOT_DATABASE_URL`, `DRUG_DATABASE_URL`, `SYMPTOM_DATABASE_URL`, etc. — so the same `alembic.ini` template can be used but each service points to its own DB URL.

### 2.3 Migration Naming Convention

Migrations are numbered sequentially with a descriptive suffix: `0001_initial_schema`, `0002_add_indexes`, `0003_add_agent_trace_log`, etc. Never use Alembic's auto-generated random hash as the only identifier — always prefix with a sequence number.

### 2.4 Running Migrations

```bash
# From service directory — applies all pending migrations
alembic upgrade head

# Roll back last migration
alembic downgrade -1

# Generate new migration after model changes
alembic revision --autogenerate -m "add_columns_to_chat_messages"

# Show current migration state
alembic current

# Show full migration history
alembic history
```

### 2.5 Startup Migration

Every service's `main.py` runs `alembic upgrade head` programmatically during startup before the FastAPI app begins accepting requests. This ensures the database is always at the correct schema version when the service starts, including after rolling updates.

---

## 3. API Contracts — Complete Request/Response Shapes

All responses follow the standard envelope:
- Success: `{"success": true, "data": {...}}`
- Error: `{"success": false, "error": "User-facing message", "error_code": "MACHINE_READABLE_CODE"}`

All authenticated endpoints require `Authorization: Bearer {jwt_token}` header.

---

### 3.1 auth-service

**POST /auth/register**

Request:
```json
{"email": "user@example.com", "password": "MinLen8HasNumber1!", "language_preference": "en"}
```
Validation: email format, password min 8 chars with at least one uppercase, one number.
Response (201):
```json
{"success": true, "data": {"user_id": "uuid", "email": "user@example.com", "message": "Verification email sent. Please check your inbox."}}
```
Errors: `EMAIL_ALREADY_EXISTS` (409), `INVALID_PASSWORD_FORMAT` (422)

---

**POST /auth/login**

Request:
```json
{"email": "user@example.com", "password": "password123", "device_info": "Mozilla/5.0..."}
```
Response if OTP not required (200):
```json
{"success": true, "data": {"access_token": "jwt...", "refresh_token": "uuid...", "token_type": "Bearer", "expires_in": 86400, "user": {"id": "uuid", "email": "...", "role": "user", "language_preference": "en", "email_verified": true}}}
```
Response if OTP required (200 but prompts OTP):
```json
{"success": true, "data": {"otp_required": true, "otp_token": "temporary-uuid", "message": "OTP sent to your email."}}
```
Errors: `INVALID_CREDENTIALS` (401), `EMAIL_NOT_VERIFIED` (403), `ACCOUNT_DEACTIVATED` (403)

---

**POST /auth/refresh**

Request:
```json
{"refresh_token": "uuid..."}
```
Response (200):
```json
{"success": true, "data": {"access_token": "new-jwt...", "refresh_token": "new-uuid...", "expires_in": 86400}}
```
Errors: `INVALID_REFRESH_TOKEN` (401), `REFRESH_TOKEN_EXPIRED` (401)

---

**POST /auth/otp/verify**

Request:
```json
{"user_id": "uuid", "code": "123456", "purpose": "email_verify"}
```
Response (200):
```json
{"success": true, "data": {"verified": true, "message": "Email verified successfully."}}
```
Errors: `INVALID_OTP` (400), `OTP_EXPIRED` (400), `OTP_MAX_ATTEMPTS` (429)

---

**POST /auth/validate** (internal — called by API Gateway only)

Request:
```json
{"token": "jwt..."}
```
Response (200):
```json
{"success": true, "data": {"valid": true, "user_id": "uuid", "role": "user", "email_verified": true, "jti": "uuid"}}
```
Response (401):
```json
{"success": false, "error": "Token invalid or expired", "error_code": "INVALID_TOKEN"}
```

---

### 3.2 chatbot-service

**POST /chat/sessions** (create new session)

Response (201):
```json
{"success": true, "data": {"session_id": "uuid", "title": "New Conversation", "created_at": "ISO8601"}}
```

---

**POST /chat/message**

Request:
```json
{
  "session_id": "uuid",
  "content": "What are the side effects of ibuprofen?",
  "input_type": "text",
  "language": "en"
}
```
This endpoint initiates a streaming WebSocket response. The HTTP response acknowledges receipt:
```json
{"success": true, "data": {"message_id": "uuid", "session_id": "uuid", "stream_url": "/ws/chat/uuid"}}
```
All content (tokens, progress, citations, visuals) arrives via WebSocket. See Section 4.

---

**POST /chat/upload**

Request: `multipart/form-data` with fields:
- `session_id`: UUID string
- `file`: file bytes
- `file_type`: pdf / docx / image

Response (202 — processing async):
```json
{"success": true, "data": {"file_id": "uuid", "status": "processing", "message": "File received. Indexing in progress."}}
```

---

**POST /chat/voice/transcribe**

Request: `multipart/form-data`:
- `session_id`: UUID
- `audio`: audio bytes (WAV or WebM)
- `language`: en / ar

Response (200):
```json
{"success": true, "data": {"transcript": "What are the side effects of ibuprofen?", "confidence": 0.97, "language_detected": "en"}}
```

---

**POST /chat/sessions/{id}/share**

Request:
```json
{"expires_in_days": 7}
```
Response (200):
```json
{"success": true, "data": {"share_url": "https://app.maisys.x/chat/share/TOKEN", "token": "TOKEN", "expires_at": "ISO8601"}}
```

---

**GET /chat/sessions/{id}/messages**

Query params: `?page=1&per_page=20&order=asc`
Response (200):
```json
{
  "success": true,
  "data": {
    "messages": [
      {"id": "uuid", "role": "user", "content": "...", "input_type": "text", "created_at": "ISO8601"},
      {"id": "uuid", "role": "assistant", "content": "...", "citations": [...], "visual_id": "uuid", "source_tier": "local", "created_at": "ISO8601"}
    ],
    "total": 42,
    "page": 1,
    "per_page": 20
  }
}
```

---

### 3.3 drug-service

**POST /drug/interaction/drug-drug**

Request:
```json
{
  "drug_names": ["warfarin", "aspirin", "ibuprofen"],
  "language": "en",
  "user_profile": {"is_pregnant": false, "chronic_conditions": ["hypertension"]}
}
```
Initiates streaming. HTTP response:
```json
{"success": true, "data": {"session_id": "uuid", "normalized_drugs": [{"original_name": "warfarin", "canonical_name": "warfarin", "rxcui": "11289", "duplicate_flag": false}, ...], "pair_count": 3, "stream_url": "/ws/drug/uuid"}}
```
Final result delivered via WebSocket `result_complete` event:
```json
{
  "event": "result_complete",
  "data": {
    "session_id": "uuid",
    "pairs": [
      {
        "drug_a": "warfarin", "drug_b": "aspirin",
        "severity": "major",
        "severity_color": "red",
        "mechanism": "Additive anticoagulant effect...",
        "clinical_significance": "Increased bleeding risk...",
        "recommendation": "Avoid combination unless benefit clearly outweighs risk...",
        "high_risk_populations": ["Elderly", "History of GI bleeding"],
        "source_tier": "web",
        "source_label": "🌐 Drugs.com",
        "citations": [{"name": "Drugs.com Interaction Checker", "url": "https://www.drugs.com/drug_interactions.html"}]
      }
    ],
    "overall_risk": "major",
    "overall_risk_color": "red",
    "overall_summary": "2 of 3 combinations have major interactions. Review urgently before use.",
    "duplicate_warnings": [],
    "disclaimer": "This information is for educational purposes only..."
  }
}
```

---

**POST /drug/profile**

Request:
```json
{"drug_name": "metformin", "language": "en"}
```
Response delivered via WebSocket (streaming), final `result_complete` event:
```json
{
  "session_id": "uuid",
  "drug_name": "metformin",
  "canonical_name": "metformin",
  "rxcui": "860975",
  "brand_names": ["Glucophage", "Fortamet", "Glumetza"],
  "drug_class": "Biguanides / Antidiabetics",
  "mechanism_of_action": "...",
  "approved_indications": ["Type 2 diabetes mellitus"],
  "dosage_summary": "500–2000 mg/day in divided doses",
  "available_forms": ["Tablet", "Extended-release tablet", "Oral solution"],
  "common_side_effects": ["Nausea", "Diarrhea", "Abdominal discomfort"],
  "serious_side_effects": ["Lactic acidosis (rare but serious)"],
  "contraindications": ["Severe renal impairment (eGFR <30)", "Metabolic acidosis"],
  "serious_warnings": ["Hold before contrast procedures", "Monitor renal function"],
  "source_tier": "local",
  "source_label": "✅ Local Knowledge Base",
  "citations": [{"source": "Drugs.com Professional", "section": "CLINICAL PHARMACOLOGY"}],
  "disclaimer": "..."
}
```

---

**POST /drug/dosage**

Request:
```json
{
  "drug_name": "amoxicillin",
  "indication": "otitis media",
  "patient_weight_kg": 20,
  "egfr": null,
  "child_pugh_score": null,
  "language": "en"
}
```
Response (streamed, final event):
```json
{
  "drug_name": "amoxicillin",
  "indication": "Otitis media",
  "adult_dose": "500 mg every 8 hours or 875 mg every 12 hours",
  "pediatric_dose_calculated": {
    "dose_per_kg": "40-90 mg/kg/day",
    "patient_weight_kg": 20,
    "calculated_daily_dose": "800-1800 mg/day",
    "divided_doses": "267-600 mg every 8 hours",
    "note": "Use the lower end for mild infections, higher end for severe"
  },
  "max_daily_dose": "3000 mg/day in adults; 90 mg/kg/day in children",
  "renal_adjustment": null,
  "hepatic_adjustment": null,
  "source_tier": "local",
  "disclaimer": "All dosing must be confirmed with a licensed prescriber or pharmacist before administration."
}
```

---

### 3.4 symptom-service

**POST /symptom/session/start**

Request:
```json
{
  "age": 35,
  "sex": "female",
  "chief_complaint": "I've had a severe headache and fever for two days",
  "language": "en"
}
```
Response (200):
```json
{
  "success": true,
  "data": {
    "session_id": "d083e76f-3c29-44aa-8893-587f3691c0c5",
    "parsed_symptoms": [
      {"id": "s_1193", "name": "Headache", "choice_id": "present"},
      {"id": "s_98", "name": "Fever", "choice_id": "present"}
    ],
    "first_question": {
      "rephrased": "Do you have any stiffness in your neck — does it hurt to move your head forward?",
      "clinical": "Do you have neck stiffness?",
      "symptom_id": "s_418",
      "answer_options": ["Yes", "No", "Not sure"]
    },
    "initial_conditions": [
      {"id": "c_150", "name": "Tension headache", "probability": 0.38},
      {"id": "c_26", "name": "Migraine", "probability": 0.31},
      {"id": "c_74", "name": "Meningitis", "probability": 0.08}
    ],
    "turn": 0,
    "max_turns": 8,
    "stream_url": "/ws/symptom/d083e76f-3c29-44aa-8893-587f3691c0c5"
  }
}
```

---

**POST /symptom/session/{session_id}/answer**

Request:
```json
{
  "symptom_id": "s_418",
  "user_answer": "No, my neck feels fine",
  "question_asked": "Do you have any stiffness in your neck?"
}
```
Response when continuing (200):
```json
{
  "success": true,
  "data": {
    "parsed_choice": "absent",
    "turn": 1,
    "next_question": {
      "rephrased": "Is the headache only on one side of your head?",
      "clinical": "Is the headache unilateral?",
      "symptom_id": "s_1264",
      "answer_options": ["Yes", "No", "Not sure"]
    },
    "current_conditions": [
      {"id": "c_26", "name": "Migraine", "probability": 0.45},
      {"id": "c_150", "name": "Tension headache", "probability": 0.35}
    ],
    "should_stop": false
  }
}
```

---

**GET /symptom/session/{session_id}/results**

Response (200) — available after stop condition reached:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid",
    "conditions": [
      {"id": "c_26", "name": "Migraine", "probability": 0.62, "common_name": "Migraine headache"},
      {"id": "c_150", "name": "Tension headache", "probability": 0.28},
      {"id": "c_500", "name": "Viral infection", "probability": 0.07}
    ],
    "triage_level": "consultation",
    "triage_color": "yellow",
    "triage_action": "Schedule a doctor's appointment within the next few days",
    "explanation": "Based on your symptoms — severe one-sided headache, fever, sensitivity to light, and nausea — migraine is the most likely explanation...",
    "triage_summary": "Your symptoms suggest you should see a doctor soon, but this is not an emergency. If you develop neck stiffness, confusion, or your symptoms suddenly worsen significantly, seek emergency care immediately.",
    "background_info": "Migraine is a neurological condition characterized by recurrent headaches...",
    "background_sources": [{"source": "Mayo Clinic", "url": "...", "section": "Symptoms"}],
    "turns_completed": 6,
    "disclaimer": "This assessment is for educational purposes only and is not a medical diagnosis..."
  }
}
```

---

### 3.5 lab-service

**POST /lab/upload**

Request: `multipart/form-data`:
- `file`: file bytes
- `language`: en / ar

Response (202):
```json
{"success": true, "data": {"session_id": "uuid", "status": "processing", "file_type": "pdf", "stream_url": "/ws/lab/uuid"}}
```

---

**GET /lab/sessions/{id}/results**

Response (200):
```json
{
  "success": true,
  "data": {
    "session_id": "uuid",
    "summary": {
      "summary_text": "22 of 24 tests are within normal range. Two tests require attention...",
      "urgency_level": "routine",
      "total_tests": 24,
      "normal_count": 22,
      "high_count": 1,
      "low_count": 1,
      "critical_count": 0
    },
    "tests": [
      {
        "id": "uuid",
        "test_name": "Hemoglobin",
        "value": "11.2",
        "unit": "g/dL",
        "reference_range": "12.0-16.0",
        "status": "low",
        "flag": "L",
        "section": "CBC",
        "explanation": {
          "what_it_measures": "Hemoglobin measures the oxygen-carrying protein in red blood cells.",
          "what_result_means": "Your hemoglobin of 11.2 g/dL is below the normal range of 12.0–16.0 g/dL, indicating mild anemia.",
          "possible_causes": "Iron deficiency, vitamin B12 or folate deficiency, chronic disease, or recent blood loss.",
          "affecting_factors": "Altitude, hydration status, and certain medications can affect hemoglobin levels.",
          "urgency_level": "discuss"
        }
      }
    ],
    "visuals": [
      {"id": "uuid", "visual_type": "chart", "chart_subtype": "bar", "title": "Test Results Overview"}
    ]
  }
}
```

---

### 3.6 research-service

**POST /research/sessions/{id}/papers/discover**

Request:
```json
{"description": "Recent studies on SGLT2 inhibitors for heart failure with preserved ejection fraction"}
```
Response (202 — job queued):
```json
{"success": true, "data": {"job_id": "uuid", "status": "queued", "stream_url": "/ws/research/session-uuid"}}
```

Final discovery result via WebSocket `discovery_complete` event:
```json
{
  "event": "discovery_complete",
  "data": {
    "job_id": "uuid",
    "total_found": 15,
    "added_to_workspace": [
      {"paper_id": "uuid", "title": "EMPEROR-Preserved Trial...", "year": 2021, "status": "indexed"}
    ],
    "pending_upload": [
      {
        "title": "Effects of Empagliflozin on HFpEF...",
        "authors": ["Anker SD", "Butler J"],
        "year": 2021,
        "doi": "10.1056/NEJMoa2107038",
        "abstract": "Background: Heart failure with preserved ejection fraction...",
        "publisher_url": "https://www.nejm.org/doi/...",
        "upload_slot_id": "uuid",
        "message": "This paper requires manual download. Visit the link above, download the PDF, and use the Upload button below."
      }
    ],
    "failed": []
  }
}
```

---

## 4. WebSocket and Streaming Event Contracts

All services use the same WebSocket connection pattern. The connection URL is `wss://api.maisys.x/ws/{service}/{session_id}`. All events are JSON strings.

### 4.1 Universal Event Types (All Services)

```json
{"event": "connected", "session_id": "uuid"}

{"event": "progress", "step": "rag_retrieval", "message": "Searching medical knowledge base...", "detail": null, "progress": 30, "eta_seconds": 8}

{"event": "agent_start", "agent_name": "InteractionAgent", "trace_id": "uuid"}
{"event": "node_start", "agent_name": "InteractionAgent", "node_name": "rag_retrieval", "input_summary": "Searching DRUG INTERACTIONS for warfarin+aspirin"}
{"event": "node_complete", "agent_name": "InteractionAgent", "node_name": "rag_retrieval", "duration_ms": 312, "output_summary": "5 chunks retrieved", "tokens_used": 0}
{"event": "node_error", "agent_name": "InteractionAgent", "node_name": "rag_retrieval", "error_type": "QdrantTimeout", "will_retry": true, "retry_count": 1}
{"event": "node_skipped", "agent_name": "InteractionAgent", "node_name": "web_search", "reason": "RAG sufficiency passed"}
{"event": "tool_call", "tool_name": "drugs_com_scraper", "input_summary": "Navigating Drugs.com: warfarin + aspirin"}
{"event": "tool_result", "tool_name": "drugs_com_scraper", "success": true, "output_summary": "1 major interaction found", "duration_ms": 4200}
{"event": "agent_complete", "agent_name": "InteractionAgent", "total_duration_ms": 5100, "total_tokens": 840}
```

### 4.2 LLM Streaming Token Events

```json
{"event": "token", "token": "Ibuprofen", "message_id": "uuid"}
{"event": "token", "token": " is", "message_id": "uuid"}
{"event": "token", "token": " a", "message_id": "uuid"}
{"event": "stream_complete", "message_id": "uuid", "total_tokens": 342}
```

### 4.3 Citation Event (After Stream Complete)

```json
{
  "event": "citations",
  "message_id": "uuid",
  "citations": [
    {"source": "Drugs.com Professional", "title": "Ibuprofen Prescribing Information", "url": "https://www.drugs.com/pro/ibuprofen", "section": "DRUG INTERACTIONS"},
    {"source": "MedlinePlus", "title": "Ibuprofen", "url": "https://medlineplus.gov/druginfo/meds/a682159.html", "section": "Drug interactions"}
  ],
  "source_tier": "local",
  "source_label": "✅ Local Knowledge Base"
}
```

### 4.4 Visual Ready Event

```json
{
  "event": "visual_ready",
  "visual_type": "chart",
  "chart_subtype": "bar",
  "title": "Drug Interaction Severity Overview",
  "visual_id": "uuid",
  "html_content": "<!DOCTYPE html>...(full self-contained HTML with Chart.js)...",
  "trigger_reason": "Response contains severity data for 3 drug pairs"
}
```

### 4.5 Emergency Event

```json
{
  "event": "emergency_detected",
  "message": "⚠️ Your symptoms may indicate a medical emergency.",
  "actions": [
    "Call emergency services (911 / 999 / 112) immediately",
    "Go to the nearest emergency room",
    "Do not drive yourself — call an ambulance"
  ],
  "arabic_message": "⚠️ قد تشير أعراضك إلى حالة طوارئ طبية.",
  "do_not_wait": true,
  "session_halted": true
}
```

### 4.6 Result Complete Events (Per Service)

Sent after all streaming, citations, and visuals are delivered:

```json
{"event": "result_complete", "session_id": "uuid", "source_tier": "local", "total_duration_ms": 3200}
```

### 4.7 Error Event

```json
{
  "event": "error",
  "error_code": "INFERMEDICA_TIMEOUT",
  "message": "The symptom assessment service is temporarily unavailable. Please try again in a moment.",
  "partial_result": null,
  "can_retry": true
}
```

---

## 5. Safety Service — Complete Specification

### 5.1 Emergency Keyword Detection Algorithm

The emergency detection runs in two stages. Stage 1 is a fast O(n) string scan using compiled regex patterns. Stage 2 is an LLM confirmation for ambiguous cases that partially match patterns but require semantic understanding.

**Stage 1 — Fast Pattern Match:**
Input text is lowercased and normalized (remove diacritics, normalize Arabic hamza forms, collapse whitespace). The normalized text is scanned against two sets of compiled regex patterns: English patterns and Arabic patterns. If any pattern matches → immediately flag as emergency (return without Stage 2).

**Stage 2 — LLM Confirmation (ambiguous cases only):**
Some phrases partially match emergency patterns but may not be emergencies (e.g. "I read about chest pain" vs "I have chest pain"). A short list of ambiguous-case triggers sends the text to a small, fast LLM call with the prompt: "Is this text describing a current medical emergency happening to the person right now? Answer only YES or NO." Temperature 0. If YES → emergency. If NO → not emergency. This call uses the smallest available fast model (Groq LLaMA-3.1-8B or GPT-4o-mini) and has a 5-second timeout.

### 5.2 Complete Emergency Keyword Lists

**English Emergency Patterns:**

```
Direct symptom patterns (Stage 1 — immediate):
- chest pain | chest tightness | chest pressure | pain in my chest | heart pain
- can't breathe | cannot breathe | difficulty breathing | shortness of breath | not breathing
- stroke | facial drooping | arm weakness | speech difficulty | sudden numbness
- unconscious | unresponsive | passed out | not responding | fainted | collapse
- seizure | convulsion | fitting | epileptic attack
- severe bleeding | uncontrolled bleeding | bleeding won't stop | blood everywhere
- anaphylaxis | severe allergic reaction | throat closing | tongue swelling | can't swallow
- overdose | took too many | accidental ingestion | swallowed too much | poisoning
- suicidal | want to die | going to kill myself | end my life | suicide
- heart attack | cardiac arrest | myocardial infarction
- severe abdominal pain | abdomen rigid | guarding (medical context)
- head injury | skull fracture | severe head trauma
- child swallowed | baby swallowed | infant ingested
- ambulance | emergency room | ER now | call 911
```

**Arabic Emergency Patterns (transliterated + Arabic script):**

```
Arabic script patterns (compiled as Unicode):
- ألم في الصدر | ضيق في الصدر | وجع في القلب | ألم قلبي
- صعوبة في التنفس | ما أقدر أتنفس | ما أقدر أنفس | لهاث شديد
- سكتة دماغية | شلل | تدلي وجه | ضعف مفاجئ
- فقدان الوعي | إغماء | فقدان الاستجابة | ما يرد علي
- نوبة صرع | تشنجات | تشنج | نوبة
- نزيف حاد | نزيف ما يوقف | نزيف شديد
- حساسية شديدة | حساسية مفاجئة | تورم الحلق | ما أقدر أبلع
- جرعة زائدة | ابتلع كثير من الدواء | تسمم | ابتلع أدوية
- أفكار انتحارية | بدي أموت | أنهي حياتي | انتحار
- أزمة قلبية | سكتة قلبية | توقف القلب
- ألم في البطن الشديد | بطن منتفخ وصلب
- الطفل ابتلع | الرضيع ابتلع | الصغير أكل دواء
- إسعاف | طوارئ الآن | اتصل بالإسعاف
```

### 5.3 Emergency Response Payload

When emergency is detected, safety-service returns:

```json
{
  "is_emergency": true,
  "severity": "critical",
  "detected_pattern": "chest_pain",
  "emergency_response": {
    "title_en": "⚠️ This may be a medical emergency",
    "title_ar": "⚠️ قد تكون هذه حالة طوارئ طبية",
    "message_en": "Your message contains symptoms that may indicate a serious medical emergency. Please stop using this app and seek immediate medical help.",
    "message_ar": "رسالتك تحتوي على أعراض قد تشير إلى حالة طوارئ طبية خطيرة. يرجى التوقف عن استخدام هذا التطبيق وطلب المساعدة الطبية الفورية.",
    "actions_en": [
      "Call emergency services immediately (911 in US, 999 in UK, 112 in EU, 911/920000 in Saudi Arabia)",
      "Go to the nearest emergency room",
      "If safe to do so — do not drive yourself, call an ambulance"
    ],
    "actions_ar": [
      "اتصل بالإسعاف فوراً (911 أو 911 السعودية 920000)",
      "اذهب إلى أقرب غرفة طوارئ",
      "إذا كان ذلك آمناً، لا تقود السيارة بنفسك — اطلب سيارة إسعاف"
    ],
    "do_not_wait": true,
    "session_should_halt": true
  }
}
```

When no emergency:
```json
{"is_emergency": false}
```

### 5.4 Triage Level → UI Behavior Mapping

| Infermedica Level | Color | Badge Text | UI Behavior |
|---|---|---|---|
| `emergency` | `#DC2626` (red-600) | 🔴 EMERGENCY | Full-screen alert overlay. Session halted. Emergency contact numbers prominently shown. Export disabled. |
| `emergency_ambulance` | `#DC2626` (red-600) | 🔴 CALL AMBULANCE | Same as emergency. |
| `consultation_24` | `#EA580C` (orange-600) | 🟠 See a Doctor Today | Orange banner at top of results. Bolded action text. |
| `consultation` | `#CA8A04` (yellow-600) | 🟡 Schedule Appointment | Yellow banner. Normal action text. |
| `self_care` | `#16A34A` (green-600) | 🟢 Home Care | Green banner. Monitoring guidance shown. |

### 5.5 Safety Service API Contracts

**POST /safety/check**

Request:
```json
{"text": "I have been having chest pain and difficulty breathing", "language": "en", "session_id": "uuid"}
```
Response — emergency:
```json
{"success": true, "data": {"is_emergency": true, "emergency_response": {...as above...}}}
```
Response — safe:
```json
{"success": true, "data": {"is_emergency": false}}
```
Timeout: 3 seconds maximum (safety check must be fast — it runs before every request).

---

**POST /safety/wrap**

Request:
```json
{
  "response_content": "Ibuprofen is a nonsteroidal anti-inflammatory drug...",
  "language": "en",
  "user_profile": {"is_pregnant": true, "chronic_conditions": ["hypertension"]},
  "context": "drug_profile",
  "drug_names": ["ibuprofen"]
}
```
Response:
```json
{
  "success": true,
  "data": {
    "wrapped_content": "Ibuprofen is a nonsteroidal anti-inflammatory drug...",
    "profile_warnings": [
      {
        "type": "pregnancy_warning",
        "severity": "high",
        "message_en": "⚠️ PREGNANCY ALERT: Ibuprofen should be avoided during pregnancy, especially in the third trimester, due to risk of harm to the developing baby. Consult your obstetrician before use.",
        "message_ar": "⚠️ تنبيه للحمل: يجب تجنب الإيبوبروفين خلال الحمل، خاصة في الثلث الثالث..."
      }
    ],
    "disclaimer_en": "This information is for educational purposes only and does not constitute medical advice. Always consult a qualified healthcare professional before making any health decisions.",
    "disclaimer_ar": "هذه المعلومات لأغراض تعليمية فقط ولا تشكل نصيحة طبية. استشر دائماً أخصائيًا صحيًا مؤهلًا قبل اتخاذ أي قرارات صحية."
  }
}
```

---

## 6. Auth Service — Complete Specification

### 6.1 JWT Token Structure

**Access Token Claims:**
```json
{
  "sub": "user-uuid",
  "jti": "unique-token-uuid",
  "role": "user",
  "email_verified": true,
  "iat": 1717000000,
  "exp": 1717086400,
  "iss": "maisys-auth"
}
```

**Refresh Token:** A UUID stored as `token_hash` (SHA-256) in the database. The raw UUID is sent to the client. On refresh, the client sends the raw UUID, the server hashes it and looks it up. On successful refresh, old refresh token is revoked and a new one is issued (rotation).

**Admin JWT uses a different secret key and includes `admin: true` claim.**

### 6.2 Password Requirements

Minimum 8 characters. Must contain: at least one uppercase letter, at least one lowercase letter, at least one digit. Maximum 128 characters. Common passwords rejected (checked against a list of top-10,000 common passwords). These rules are enforced in the service — never rely on frontend validation alone.

### 6.3 OTP Flow Details

OTP codes are 6-digit numeric strings. Generated using `secrets.randbelow(900000) + 100000` (guarantees 6 digits, cryptographically random). Stored as bcrypt hash in `otp_codes.code_hash` with cost factor 10 (faster than password hashing — OTPs expire quickly and need fast verification).

Maximum 5 verification attempts per OTP code. On 5th failed attempt, the code is invalidated regardless of expiry. A new OTP request is required.

OTP codes are purpose-specific — an `email_verify` OTP cannot be used for `password_reset`. The purpose field is checked on verification.

Resend OTP: allowed after 60-second cooldown per purpose per user.

### 6.4 Google OAuth Flow

1. Frontend redirects user to Google OAuth URL with `client_id`, `redirect_uri`, `scope=email profile`, `response_type=code`, `state=CSRF-token`
2. Google authenticates user and redirects to `/auth/oauth/google` with `code` and `state`
3. auth-service verifies CSRF state token
4. auth-service exchanges `code` for Google access token via server-side HTTP POST to Google token endpoint
5. auth-service calls Google userinfo endpoint to get email and provider user ID
6. auth-service looks up `oauth_accounts` table for `(provider=google, provider_user_id)`
7. If found: log in existing user → issue JWT + refresh token
8. If not found: check if email already exists in `users` table
   - If yes: link OAuth account to existing user → issue JWT
   - If no: create new user with `email_verified=true` (Google already verified the email) → create OAuth account → issue JWT
9. Google access token is discarded — never stored

### 6.5 Session Revocation

On logout: refresh token revoked in database (`revoked=true`, `revoked_at=now()`). JWT itself cannot be revoked (stateless) — it expires naturally in 24 hours. For "sign out all devices": all refresh tokens for the user are revoked, and all entries in the `sessions` table for the user are set to `revoked=true`. The API Gateway calls `/auth/validate` on each request and checks the `jti` against the `sessions` table. If `revoked=true` → 401 even if JWT signature is valid.

---

## 7. Notification Service — Complete Specification

### 7.1 RabbitMQ Message Format

All notification requests arrive via the `notification.send` queue with this message format:
```json
{
  "notification_type": "email_verify",
  "user_id": "uuid",
  "recipient_email": "user@example.com",
  "language": "en",
  "template_name": "email_verify",
  "template_vars": {
    "otp_code": "847291",
    "expires_in_minutes": 10,
    "user_name": "Ahmad"
  },
  "correlation_id": "uuid",
  "priority": "high"
}
```

Priority levels: `high` (OTP codes — deliver immediately), `normal` (export ready notifications), `low` (informational).

### 7.2 Email Templates

All templates are bilingual — language chosen based on `language` field in the message.

**Template: `email_verify`**
Subject EN: "Verify your MAISYS email address"
Subject AR: "تحقق من عنوان بريدك الإلكتروني في MAISYS"
Body: OTP code prominently displayed, expires in 10 minutes, link to verification page.

**Template: `password_reset`**
Subject EN: "Reset your MAISYS password"
Subject AR: "إعادة تعيين كلمة مرور MAISYS"
Body: OTP code for password reset, 10-minute expiry, security notice.

**Template: `login_otp`**
Subject EN: "Your MAISYS login code"
Subject AR: "رمز تسجيل الدخول إلى MAISYS"
Body: 6-digit code, valid for 10 minutes, security warning if not requested by user.

**Template: `export_ready`**
Subject EN: "Your MAISYS export is ready"
Subject AR: "تصديرك من MAISYS جاهز"
Body: Link to download file, expires in 24 hours.

**Template: `beta_session_reviewed`**
Subject EN: "Your MAISYS Beta feedback has been reviewed"
Body: Thank-you message confirming the session was reviewed by medical staff, no individual results shared.

### 7.3 Retry Logic

Failed email deliveries are retried 3 times with exponential backoff: 1 minute, 5 minutes, 30 minutes. After 3 failures, the notification is logged as `failed` in `notification_log` with the error detail. An alert is sent to the monitoring system for persistent failures.

If the primary provider (SendGrid) fails: automatic fallback to SMTP for the retry attempt.

### 7.4 Email Security

All emails include: unsubscribe link (for non-OTP emails), SPF/DKIM/DMARC alignment (configured on the domain), no user PII in email subjects, no session content in export-ready emails (only a download link with a secure token).

---

## 8. Frontend — Component Trees and State Per Page

### 8.1 Global Redux State Shape

```typescript
interface RootState {
  auth: {
    user: User | null;               // null = unauthenticated
    accessToken: string | null;
    isLoading: boolean;
    error: string | null;
  };
  theme: {
    mode: 'light' | 'dark';
    language: 'en' | 'ar';
    isRTL: boolean;
  };
  chatbot: {
    sessions: ChatSession[];
    activeSessionId: string | null;
    messages: Record<string, ChatMessage[]>;  // keyed by session_id
    isStreaming: boolean;
    streamBuffer: string;                     // accumulates streaming tokens
    agentActivity: AgentEvent[];
    pendingVisuals: string[];                 // visual_ids being generated
  };
  drug: {
    activeFeature: DrugFeature;
    sessions: DrugSession[];
    currentResult: DrugResult | null;
    normalizedDrugs: NormalizedDrug[];
    isProcessing: boolean;
    agentActivity: AgentEvent[];
  };
  symptom: {
    alphaSession: SymptomSession | null;
    betaSession: BetaSession | null;
    currentQuestion: Question | null;
    isFinalized: boolean;
    results: SymptomResult | null;
  };
  lab: {
    sessions: LabSession[];
    activeSessionId: string | null;
    tests: Record<string, LabTest[]>;
    isProcessing: boolean;
    processingProgress: number;
  };
  research: {
    sessions: ResearchSession[];
    activeSessionId: string | null;
    papers: Record<string, Paper[]>;
    pendingUploads: PendingPaper[];
    messages: Record<string, ChatMessage[]>;
    isDiscovering: boolean;
    discoveryProgress: number;
  };
  notifications: {
    toasts: Toast[];
  };
}
```

### 8.2 Key Pages — Component Tree and API Calls

**Page 13 — Main Dashboard (`/dashboard`)**

Component tree:
```
DashboardPage
├── WelcomeBanner (user name, last login)
├── ModuleGrid
│   ├── ModuleCard (chatbot)
│   ├── ModuleCard (drug)
│   ├── ModuleCard (symptom)
│   ├── ModuleCard (lab)
│   └── ModuleCard (research)
├── RecentActivity
│   └── SessionListItem × 5 (across all modules)
├── HealthProfilePrompt (if profile incomplete)
└── BetaCTA (if eligible and not enrolled)
```

API calls on mount:
- GET `/chat/sessions?per_page=2&order=desc` (last 2 chatbot sessions)
- GET `/drug/sessions?per_page=2` (last 2 drug sessions)
- GET `/symptom/sessions?per_page=2`
- GET `/lab/sessions?per_page=2`
- GET `/research/sessions?per_page=2`
- GET `/chat/profile` (health profile completion status)

Redux slices updated: chatbot.sessions, drug.sessions, symptom.sessions, lab.sessions, research.sessions

---

**Page 19 — Medical Chatbot (`/chatbot`)**

Component tree:
```
ChatbotPage
├── SessionSidebar
│   ├── NewSessionButton
│   ├── SearchBar
│   └── SessionList
│       └── SessionItem × N (title, date, starred indicator)
├── ChatArea
│   ├── ChatHeader (title, share button, export button)
│   ├── MessageList
│   │   └── MessageBubble × N
│   │       ├── MessageContent (streaming text or full text)
│   │       ├── CitationList (source badges)
│   │       ├── VisualFrame (iframe with chart/infographic/diagram HTML)
│   │       └── FeedbackButtons (like/dislike)
│   ├── AgentActivityPanel (collapsible)
│   │   └── AgentRow × N
│   │       └── NodeStep × M (pulsing/complete/error/skipped)
│   └── InputArea
│       ├── TextInput (multiline, enter to send)
│       ├── VoiceButton (hold to record)
│       ├── AttachButton (file/image picker)
│       └── SendButton
└── HealthProfileDrawer (slides in from right)
```

State managed: chatbot Redux slice
WebSocket: connected on session open, disconnected on navigate away
API calls:
- GET `/chat/sessions` (on mount — load session list)
- POST `/chat/sessions` (new session)
- GET `/chat/sessions/{id}/messages` (on session select)
- POST `/chat/message` (on send — initiates WebSocket streaming)
- POST `/chat/upload` (on file/image attach)
- POST `/chat/voice/transcribe` (on voice stop)
- POST `/chat/sessions/{id}/share` (on share click)

---

**Page 20 — Drug Agent (`/drugs`)**

Component tree:
```
DrugAgentPage
├── FeatureTabBar (12 tabs — profile / interactions / food / disease / pregnancy / dosage / alternatives / comparison / pk / off-label / brand-generic / class-browser)
├── ActiveFeaturePanel (renders based on activeFeature)
│   ├── DrugInputArea
│   │   ├── DrugChipInput (tag-style multi-drug input with RxNorm autocomplete)
│   │   └── AdditionalInputs (weight/eGFR for dosage, indication, etc.)
│   ├── SubmitButton
│   ├── AgentActivityPanel (collapsible)
│   ├── ResultArea
│   │   ├── StreamingText (if LLM is generating)
│   │   ├── StructuredResult (table/list depending on feature)
│   │   ├── SourceBadge (✅ Local KB or 🌐 Web Source + URL)
│   │   ├── VisualFrame (auto-triggered chart/infographic)
│   │   └── CitationList
│   └── ExportBar (TXT/DOCX/PDF buttons)
└── SessionHistory (right panel — past drug queries)
```

Drug chip input: user types drug name → debounced GET `/drug/rxnorm/suggest?q=aspir` → autocomplete dropdown shows canonical name + brand names → chip created on select showing canonical name.

**RxNorm autocomplete endpoint:** GET `/drug/rxnorm/suggest?q={partial_name}` → `{"suggestions": [{"canonical": "aspirin", "rxcui": "1191", "brands": ["Bayer", "Ecotrin"]}]}`

---

**Page 21 — Symptom Checker Alpha (`/symptoms`)**

Component tree:
```
SymptomCheckerPage
├── InitialFormPanel (shown when no active session)
│   ├── AgeInput
│   ├── SexSelector (male/female radio)
│   ├── ChiefComplaintTextarea
│   ├── LanguageSelector
│   └── StartButton
├── ConversationPanel (shown during active session)
│   ├── ParsedSymptomsDisplay (initial symptoms identified)
│   ├── ProgressIndicator (Turn {n} of max 8)
│   ├── ConditionsSidebar
│   │   └── ConditionBar × 3 (name + probability bar — updates after each turn)
│   ├── QuestionDisplay (current rephrased question)
│   ├── AnswerInput
│   │   ├── TextInput
│   │   ├── QuickAnswerButtons (Yes / No / Not Sure)
│   │   └── VoiceButton
│   └── SubmitAnswerButton
└── ResultsPanel (shown after finalization)
    ├── TriageBanner (color-coded, action text)
    ├── ConditionList
    │   └── ConditionCard × 3
    │       ├── ConditionName + ProbabilityBar
    │       └── ExpandableExplanation (streaming text)
    ├── BackgroundInfoSection (RAG enrichment content)
    ├── TriageSummary (streaming text)
    ├── DisclaimerBox
    └── ExportBar
```

---

**Page 23 — Lab Test Explainer (`/labs`)**

Component tree:
```
LabPage
├── UploadZone (drag-drop, accepts PDF/JPG/PNG/WEBP/DOCX)
├── ProcessingOverlay (shown during processing)
│   ├── ProcessingAnimation
│   ├── ProgressBar (0-100%)
│   ├── StatusMessage (streaming progress events)
│   └── TestCountBadge (updates: "Found 24 tests")
├── ResultsDashboard (shown after processing)
│   ├── UrgencyBanner (none/routine/soon/urgent color-coded)
│   ├── SummaryCard (overall summary streaming text)
│   ├── VisualFrame (auto-generated bar chart)
│   ├── TestResultsGrid
│   │   └── TestCard × N (per test — expandable)
│   │       ├── TestName + StatusBadge (normal/high/low/critical)
│   │       ├── ValueDisplay ({value} {unit} | Range: {ref_range})
│   │       └── ExplanationAccordion (streaming text per test)
│   └── ExportBar
└── FollowUpChat (below results)
    ├── MessageList
    ├── AgentActivityPanel
    └── InputArea (text + voice + image)
```

---

**Page 24 — Research Paper Assistant (`/research`)**

Component tree:
```
ResearchPage
├── SessionSidebar (same pattern as chatbot)
├── WorkspaceArea
│   ├── PaperList
│   │   ├── PaperCard × N
│   │   │   ├── PaperTitle + Authors + Year
│   │   │   ├── StatusBadge (indexed / processing / awaiting_file)
│   │   │   ├── UploadButton (for awaiting_file papers)
│   │   │   └── PaperActions (summarize / translate / Q&A)
│   │   ├── UploadPaperButton
│   │   └── DiscoverPapersButton
│   ├── DiscoveryPanel (shown during/after discovery)
│   │   ├── DiscoveryProgress
│   │   ├── AddedPapers list
│   │   └── PendingUploadList
│   │       └── PendingPaperCard × N
│   │           ├── PaperTitle + Abstract snippet
│   │           ├── PublisherLink (external)
│   │           └── UploadButton (upload slot)
│   └── ToolsTabs (Chat / Summarize / Translate / Q&A / Compare)
│       ├── ChatTab (full chatbot-equivalent UI)
│       ├── SummarizeTab (paper selector + mode selector + output)
│       ├── TranslateTab (paper selector + direction + mode + output)
│       ├── QATab (paper selector + mode + Q&A output)
│       └── CompareTab (multi-paper selector + comparison table output)
└── AgentActivityPanel
```

---

## 9. Environment Variables — Complete Reference

Every environment variable for every service. Variables marked `[SECRET]` must be stored in Kubernetes Secrets, not in ConfigMaps. Variables marked `[PER_ENV]` differ between GCP and Azure overlays.

### 9.1 Shared Variables (All Services)

```env
ENVIRONMENT=production                    # development / staging / production
LOG_LEVEL=INFO                            # DEBUG / INFO / WARNING / ERROR
CLOUD=gcp                                 # gcp / azure / aws [PER_ENV — set in Kustomize overlay]
SERVICE_NAME=chatbot-service              # Set per service in Dockerfile or K8s

# RabbitMQ
RABBITMQ_URL=amqp://user:pass@rabbitmq:5672/  # [SECRET]
RABBITMQ_EXCHANGE=maisys_topic

# Object Storage — GCP (dev) [PER_ENV]
GCS_BUCKET=maisys-dev-storage
GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-sa.json  # [SECRET]

# Object Storage — Azure (stage) [PER_ENV]
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=...  # [SECRET]
AZURE_BLOB_CONTAINER=maisys-stage-storage

# Object Storage — AWS (production) [PER_ENV]
AWS_S3_BUCKET=maisys-prod-storage
AWS_REGION=us-east-1
# AWS credentials provided via IRSA (IAM Role for Service Accounts) — no static keys needed
# The pod's service account is annotated with an IAM role ARN that grants S3 access
```

### 9.2 auth-service

```env
AUTH_DATABASE_URL=postgresql+asyncpg://user:pass@auth-postgres:5432/maisys_auth_db  # [SECRET]
AUTH_REDIS_URL=redis://auth-redis:6379/0

# JWT
JWT_SECRET_KEY=...minimum-64-char-random-string...  # [SECRET]
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440     # 24 hours
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Admin JWT (separate issuer)
ADMIN_JWT_SECRET_KEY=...different-64-char-string...  # [SECRET]
ADMIN_JWT_ALGORITHM=HS256
ADMIN_JWT_EXPIRE_MINUTES=480             # 8 hours

# OAuth — Google
GOOGLE_CLIENT_ID=...  # [SECRET]
GOOGLE_CLIENT_SECRET=...  # [SECRET]
GOOGLE_REDIRECT_URI=https://api.maisys.x/auth/oauth/google

# OAuth — Apple
APPLE_CLIENT_ID=...  # [SECRET]
APPLE_TEAM_ID=...
APPLE_KEY_ID=...
APPLE_PRIVATE_KEY_PATH=/secrets/apple_key.p8  # [SECRET]

# OTP
OTP_EXPIRE_MINUTES=10
OTP_MAX_ATTEMPTS=5
OTP_RESEND_COOLDOWN_SECONDS=60

# Admin IP allowlist (comma-separated CIDR)
ADMIN_ALLOWED_IPS=10.0.0.0/8,192.168.1.0/24
```

### 9.3 chatbot-service

```env
CHATBOT_DATABASE_URL=postgresql+asyncpg://user:pass@chatbot-postgres:5432/maisys_chatbot_db  # [SECRET]
CHATBOT_REDIS_URL=redis://chatbot-redis:6379/0

# LLM — fetched dynamically from model-router-service at request time
MODEL_ROUTER_URL=http://model-router-service/model-router

# RAG
QDRANT_URL=http://qdrant:6333
MEDICAL_RAG_COLLECTION_MINILM=medical_minilm
MEDICAL_RAG_COLLECTION_PUBMEDBERT=medical_pubmedbert
DRUG_RAG_COLLECTION_MINILM=drug_minilm
DRUG_RAG_COLLECTION_PUBMEDBERT=drug_pubmedbert
RAG_TOP_K=8
MIN_RAG_CHUNKS=3
MIN_LLM_CONFIDENCE=0.75

# Two-tier retrieval
SERPER_API_KEY=...  # [SECRET]

# Vision
OLLAMA_URL=http://ollama:11434            # For local vision models (LLaVA, Gemma)

# STT/TTS
FASTER_WHISPER_MODEL=large-v3
ELEVENLABS_API_KEY=...  # [SECRET]
SUPERTONE_API_KEY=...  # [SECRET]

# Conversation memory
CONVERSATION_WINDOW_SIZE=10              # Full messages kept
CONVERSATION_SUMMARY_MAX_TOKENS=300
CONVERSATION_SUMMARY_TRIGGER=5          # Update summary every N new messages
CONVERSATION_HISTORY_MAX_TOKENS=2000

# Session
SESSION_SHARE_DEFAULT_EXPIRY_DAYS=7

# KV cache
KV_CACHE_MAX_ENTRIES=8
KV_CACHE_ENABLED=true

# Playwright (for visual rendering)
PLAYWRIGHT_HEADLESS=true

# Safety service
SAFETY_SERVICE_URL=http://safety-service

# Translation service
TRANSLATION_SERVICE_URL=http://translation-service
```

### 9.4 drug-service

```env
DRUG_DATABASE_URL=postgresql+asyncpg://user:pass@drug-postgres:5432/maisys_drug_db  # [SECRET]
DRUG_REDIS_URL=redis://drug-redis:6379/0

MODEL_ROUTER_URL=http://model-router-service/model-router
SAFETY_SERVICE_URL=http://safety-service
TRANSLATION_SERVICE_URL=http://translation-service

QDRANT_URL=http://qdrant:6333
DRUG_RAG_COLLECTION_MINILM=drug_minilm
DRUG_RAG_COLLECTION_PUBMEDBERT=drug_pubmedbert

# RxNorm
RXNORM_BASE_URL=https://rxnav.nlm.nih.gov/REST
RXNORM_TIMEOUT_SECONDS=5
RXNORM_CACHE_TTL_SECONDS=86400           # 24 hours

# Two-tier retrieval thresholds
MIN_RAG_CHUNKS=3
MIN_LLM_CONFIDENCE=0.75
DOSAGE_MIN_CONFIDENCE=0.85               # Higher threshold for dosage (high risk)
PK_MIN_CONFIDENCE=0.80

# Web fallback
SERPER_API_KEY=...  # [SECRET]
DRUGS_COM_INTERACTION_URL=https://www.drugs.com/drug_interactions.html
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_TIMEOUT_MS=20000

# Agent limits
INTERACTION_AGENT_MAX_ITERATIONS=5
COMPARISON_AGENT_MAX_ITERATIONS=8
DRUG_ACQUISITION_AGENT_MAX_ITERATIONS=10
AGENT_GRAPH_TIMEOUT_SECONDS=90

# Token budgets
INTERACTION_AGENT_TOKEN_BUDGET=2000
COMPARISON_AGENT_TOKEN_BUDGET=4000

# Concurrent pair analysis
MAX_CONCURRENT_PAIRS=5

# DDIMDL dataset paths and config
DDIMDL_DRUG_DATA_PATH=/data/ddimdl/drug_data.csv
DDIMDL_INTERACTIONS_PATH=/data/ddimdl/Interactions.csv
DDIMDL_ENABLED=true                      # Toggle Tier 0 lookup on/off
DDIMDL_CACHE_TTL_SECONDS=43200          # 12 hours for interaction lookup cache
DDIMDL_FEATURES_CACHE_TTL_SECONDS=86400 # 24 hours for molecular features cache
```

### 9.5 symptom-service

```env
SYMPTOM_DATABASE_URL=postgresql+asyncpg://user:pass@symptom-postgres:5432/maisys_symptom_db  # [SECRET]
SYMPTOM_REDIS_URL=redis://symptom-redis:6379/0

MODEL_ROUTER_URL=http://model-router-service/model-router
SAFETY_SERVICE_URL=http://safety-service
TRANSLATION_SERVICE_URL=http://translation-service

# Infermedica
INFERMEDICA_APP_ID=...  # [SECRET]
INFERMEDICA_APP_KEY=...  # [SECRET]
INFERMEDICA_BASE_URL=https://api.infermedica.com/v3
INFERMEDICA_TIMEOUT_SECONDS=15
INFERMEDICA_DEV_MODE=false               # MUST be false in production

# Medical RAG (for background enrichment)
QDRANT_URL=http://qdrant:6333
MEDICAL_RAG_COLLECTION_MINILM=medical_minilm
MEDICAL_RAG_COLLECTION_PUBMEDBERT=medical_pubmedbert
RAG_ENRICHMENT_TOP_K=4

# Session limits
MAX_TURNS=8
STOP_PROBABILITY_THRESHOLD=0.85
STOP_PROBABILITY_GAP=0.50

# Beta
BETA_VLLM_URL=http://vllm-server:8000/v1  # Separate vLLM endpoint for Beta model
BETA_MODEL_NAME=meditron-7b-finetuned
BETA_ENABLED=true
```

### 9.6 lab-service

```env
LAB_DATABASE_URL=postgresql+asyncpg://user:pass@lab-postgres:5432/maisys_lab_db  # [SECRET]
LAB_REDIS_URL=redis://lab-redis:6379/0

MODEL_ROUTER_URL=http://model-router-service/model-router
SAFETY_SERVICE_URL=http://safety-service
TRANSLATION_SERVICE_URL=http://translation-service

QDRANT_URL=http://qdrant:6333
MEDICAL_RAG_COLLECTION_MINILM=medical_minilm
MEDICAL_RAG_COLLECTION_PUBMEDBERT=medical_pubmedbert

# File limits
MAX_UPLOAD_SIZE_BYTES=52428800           # 50MB
MAX_PDF_PAGES=50
ACCEPTED_MIME_TYPES=application/pdf,image/jpeg,image/png,image/webp,application/vnd.openxmlformats-officedocument.wordprocessingml.document

# OCR
PRIMARY_OCR_ENGINE=paddleocr             # paddleocr / mistral / lighton / vision_llm
MISTRAL_API_KEY=...  # [SECRET]
LIGHTON_API_KEY=...  # [SECRET]
SCANNED_PDF_DETECTION_THRESHOLD_CHARS=100  # chars per first 3 pages

# Processing
MAX_CONCURRENT_EXPLANATIONS=5
EXPLANATION_SEMAPHORE_LIMIT=5
OLLAMA_URL=http://ollama:11434
```

### 9.7 research-service

```env
RESEARCH_DATABASE_URL=postgresql+asyncpg://user:pass@research-postgres:5432/maisys_research_db  # [SECRET]
RESEARCH_REDIS_URL=redis://research-redis:6379/0

MODEL_ROUTER_URL=http://model-router-service/model-router
SAFETY_SERVICE_URL=http://safety-service
TRANSLATION_SERVICE_URL=http://translation-service

QDRANT_URL=http://qdrant:6333

# Paper discovery
SEMANTIC_SCHOLAR_API_KEY=...  # [SECRET] Optional — higher rate limit with key
SEMANTIC_SCHOLAR_BASE_URL=https://api.semanticscholar.org/graph/v1
SEMANTIC_SCHOLAR_TIMEOUT_SECONDS=15
SERPER_API_KEY=...  # [SECRET]
PAPER_DOWNLOAD_TIMEOUT_SECONDS=120
MAX_DISCOVERY_RESULTS=20

# Discovery agent
PAPER_DISCOVERY_MAX_ITERATIONS=15
PAPER_DISCOVERY_TIMEOUT_SECONDS=300
MAX_CONCURRENT_INGESTION=3

# NLP tool modes
SUMMARIZATION_MODE=llm                   # model / llm
QA_MODE=llm
TRANSLATION_MODE=model

# OCR (same as lab-service)
PRIMARY_OCR_ENGINE=paddleocr
MISTRAL_API_KEY=...  # [SECRET]
LIGHTON_API_KEY=...  # [SECRET]

# Paper RAG
PAPER_CHUNK_SIZE_TOKENS=500
PAPER_CHUNK_OVERLAP_TOKENS=80

# Share
SHARE_DEFAULT_EXPIRY_DAYS=7
OLLAMA_URL=http://ollama:11434
```

### 9.8 export-service

```env
EXPORT_DATABASE_URL=postgresql+asyncpg://user:pass@export-postgres:5432/maisys_export_db  # [SECRET]

# Output storage — uses shared object storage config per cloud
# GCP dev:    GCS_BUCKET=maisys-dev-storage
# Azure stage: AZURE_BLOB_CONTAINER=maisys-stage-storage
# AWS prod:   AWS_S3_BUCKET=maisys-prod-storage
# (all inherited from shared vars — CLOUD env var determines which backend is used)
EXPORT_FILE_EXPIRY_HOURS=24
EXPORT_PATH_PREFIX=exports/

# Fonts
ARABIC_FONT_PATH=/app/fonts/NotoSansArabic.ttf
```

### 9.9 notification-service

```env
NOTIFICATION_DATABASE_URL=postgresql+asyncpg://user:pass@notification-postgres:5432/maisys_notification_db  # [SECRET]

# Email — SendGrid
SENDGRID_API_KEY=...  # [SECRET]
EMAIL_FROM_ADDRESS=noreply@maisys.x
EMAIL_FROM_NAME=MAISYS

# Email — SMTP fallback
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...  # [SECRET]
SMTP_PASSWORD=...  # [SECRET]
SMTP_USE_TLS=true
SMTP_ENABLED=true

# Retry
MAX_RETRY_ATTEMPTS=3
RETRY_DELAYS_SECONDS=60,300,1800         # 1min, 5min, 30min
```

### 9.10 model-router-service

```env
MODEL_ROUTER_DATABASE_URL=postgresql+asyncpg://user:pass@model-router-postgres:5432/maisys_model_router_db  # [SECRET]

# All provider API keys stored here — module services never hold API keys directly
OPENAI_API_KEY=sk-...  # [SECRET]
ANTHROPIC_API_KEY=sk-ant-...  # [SECRET]
GEMINI_API_KEY=...  # [SECRET]
GROQ_API_KEY=...  # [SECRET]
MISTRAL_API_KEY=...  # [SECRET]
COHERE_API_KEY=...  # [SECRET]
AZURE_OPENAI_API_KEY=...  # [SECRET]
AZURE_OPENAI_ENDPOINT=https://maisys.openai.azure.com/

# vLLM (Alpha medical LLM)
VLLM_BASE_URL=http://vllm-server:8000/v1
VLLM_MODEL_NAME=meditron-7b              # or biogpt / biomedlm / medalpaca / pmcllama

# vLLM (Beta symptom checker LLM — separate server or separate model)
BETA_VLLM_BASE_URL=http://vllm-beta-server:8000/v1
BETA_VLLM_MODEL_NAME=meditron-7b-finetuned

# Ollama (vision models)
OLLAMA_BASE_URL=http://ollama:11434

# STT/TTS keys
ELEVENLABS_API_KEY=...  # [SECRET]
SUPERTONE_API_KEY=...  # [SECRET]

# OCR keys
MISTRAL_OCR_API_KEY=...  # [SECRET]
LIGHTON_API_KEY=...  # [SECRET]

# Config cache
CONFIG_CACHE_TTL_SECONDS=30              # Module services cache active config for 30 seconds
```

### 9.11 admin-service

```env
ADMIN_DATABASE_URL=postgresql+asyncpg://user:pass@admin-postgres:5432/maisys_admin_db  # [SECRET]

# Admin JWT (same secret as in auth-service)
ADMIN_JWT_SECRET_KEY=...  # [SECRET]
ADMIN_JWT_ALGORITHM=HS256

# IP allowlist
ADMIN_ALLOWED_IPS=10.0.0.0/8

# TOTP
TOTP_ISSUER_NAME=MAISYS Admin
TOTP_VALID_WINDOW=1                      # Accept ±1 time step (30-second windows)

# Cross-service access (admin reads from other services' DBs via their APIs, not directly)
SYMPTOM_SERVICE_URL=http://symptom-service
MODEL_ROUTER_SERVICE_URL=http://model-router-service
```

### 9.12 translation-service

```env
TRANSLATION_REDIS_URL=redis://translation-redis:6379/0
TRANSLATION_CACHE_TTL_SECONDS=86400      # 24 hours

# Google Translate
GOOGLE_TRANSLATE_API_KEY=...  # [SECRET]

# LLM mode (uses model-router-service)
MODEL_ROUTER_URL=http://model-router-service/model-router

# Default mode
DEFAULT_TRANSLATION_MODE=google          # google / local / llm
MEDICAL_TRANSLATION_MODE=llm            # For medical context-sensitive translation
```

### 9.13 safety-service

```env
# Stateless — no database, no Redis
# LLM for Stage 2 ambiguous case confirmation
MODEL_ROUTER_URL=http://model-router-service/model-router
STAGE2_LLM_TIMEOUT_SECONDS=5
STAGE2_ENABLED=true

# Emergency detection config
EMERGENCY_DETECTION_LANGUAGE=both        # en / ar / both
```

### 9.14 API Gateway

```env
AUTH_SERVICE_URL=http://auth-service
AUTH_VALIDATE_ENDPOINT=/auth/validate
AUTH_VALIDATE_TIMEOUT_SECONDS=3

# Rate limiting (Redis)
GATEWAY_REDIS_URL=redis://gateway-redis:6379/0

# Routing
CHATBOT_SERVICE_URL=http://chatbot-service
DRUG_SERVICE_URL=http://drug-service
SYMPTOM_SERVICE_URL=http://symptom-service
LAB_SERVICE_URL=http://lab-service
RESEARCH_SERVICE_URL=http://research-service
AUTH_SERVICE_BACKEND_URL=http://auth-service
EXPORT_SERVICE_URL=http://export-service
ADMIN_SERVICE_URL=http://admin-service

# Max request body size
MAX_REQUEST_BODY_SIZE_BYTES=1048576      # 1MB (file upload routes override this to 52428800)
MAX_FILE_UPLOAD_SIZE_BYTES=52428800      # 50MB
```

---

*MAISYS Technical Development Guide — Part 5: Database Schemas · API Contracts · Safety Service · Auth Service · Notification Service · Frontend Detail · Environment Variables*

*End of Part 5 — Complete MAISYS Technical Development Guide (Parts 1–5)*
