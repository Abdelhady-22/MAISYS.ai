# MAISYS — Technical Development Guide
## Part 1: Platform Overview · Microservices Architecture · Services Catalog · Shared Library · Model Registry · CI/CD

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Microservices Architecture](#2-microservices-architecture)
3. [API Gateway](#3-api-gateway)
4. [Service Communication — REST + RabbitMQ](#4-service-communication--rest--rabbitmq)
5. [Layered Architecture — Standard Per Service](#5-layered-architecture--standard-per-service)
6. [Shared Library — `shared/`](#6-shared-library--shared)
7. [Complete Services Catalog](#7-complete-services-catalog)
8. [Shared Capabilities Across All Services](#8-shared-capabilities-across-all-services)
9. [Specialized NLP Tools — Model Mode vs LLM Mode](#9-specialized-nlp-tools--model-mode-vs-llm-mode)
10. [OCR Engines — Including LLM-Based OCR](#10-ocr-engines--including-llm-based-ocr)
11. [Model Registry and Admin Model Switcher](#11-model-registry-and-admin-model-switcher)
12. [Complete Model Catalog](#12-complete-model-catalog)
13. [KV Cache Architecture](#13-kv-cache-architecture)
14. [Concurrent and Batch Processing Patterns](#14-concurrent-and-batch-processing-patterns)
15. [Git Branching and CI/CD Pipeline](#15-git-branching-and-cicd-pipeline)
16. [Monorepo Project Structure](#16-monorepo-project-structure)

---

## 1. Platform Overview

MAISYS (Medical AI System) is a comprehensive web-based medical AI platform that provides trusted medical education and guidance across five intelligent modules. Each module is an independently deployable microservice sharing a common infrastructure layer and shared library.

### What MAISYS Is

An intelligent medical education platform built to make complex medical knowledge accessible, comprehensible, and actionable — in Arabic and English. It helps users understand their health, their medications, their lab results, and the medical research relevant to them.

### What MAISYS Is Not

- Not a diagnostic tool — it never diagnoses diseases or medical conditions
- Not a prescription service — it never prescribes medications or treatments
- Not an emergency service — it detects emergencies and directs users to proper care immediately
- Not a replacement for healthcare professionals — every response includes professional consultation guidance

### Core Principles

**Educational not diagnostic** — all responses are educational; diagnosis belongs to physicians.

**Grounded not hallucinated** — every response is anchored in retrieved medical documents from trusted sources. The LLM's general knowledge supplements but never replaces retrieved evidence.

**Safe by design** — emergency detection, medical disclaimers, and professional consultation reminders on every response across every module.

**Bilingual first** — Arabic and English are equal first-class citizens. The entire platform — UI, responses, exports, voices — works in both languages.

**Evidence-based** — every claim is cited with source name, document title, and relevant section.

### Platform Availability

Web application (desktop and tablet). Mobile-responsive web interface. A mobile application is also part of the MAISYS product and is currently under active development. It is not yet integrated with this backend system — integration will be addressed in a separate phase.

### Languages and Typography

When the user's language is Arabic, the entire interface and all exports switch to RTL layout.

- English font: Outfit
- Arabic font: IBM Plex Sans Arabic

---

## 2. Microservices Architecture

### Architecture Decision

MAISYS is built as a microservices system. Each module is an independently deployable service with its own database, Redis instance, and Kubernetes deployment unit. Services communicate through a combination of synchronous REST calls and asynchronous RabbitMQ messages.

### Why Microservices for MAISYS

Each module has fundamentally different computational requirements. The drug-service handles high-concurrency parallel drug pair analysis. The research-service handles large PDF uploads and long-running paper discovery jobs. The symptom-service manages multi-turn stateful sessions with an external API. The chatbot-service handles real-time streaming conversations with large knowledge bases. The lab-service processes uploaded documents with OCR pipelines. These profiles cannot share one scaling unit efficiently.

Each service also has distinct data models with no meaningful reason to share a database. Separating them eliminates cross-module query complexity and enables each service to evolve independently.

### Services Overview

Fourteen services in three groups:

**Module Services (5):** chatbot-service, drug-service, symptom-service, lab-service, research-service

**Shared Services (5):** auth-service, translation-service, export-service, safety-service, notification-service

**Infrastructure Services (4):** api-gateway, model-router-service, admin-service, frontend-service

### System Architecture Diagram

```
Internet
    ↓
Cloudflare (CDN + DDoS + SSL + Wildcard TLS)
    ↓
API Gateway ←→ auth-service (validates every request)
    ↓
    ├── chatbot-service  ←→ Medical RAG (Qdrant) + Drug RAG (Qdrant)
    │                    ←→ maisys_chatbot_db (PostgreSQL)
    │                    ←→ chatbot-redis
    │
    ├── drug-service     ←→ Drug RAG (Qdrant) — Drugs.com + Mayo drugs + MedlinePlus drugs
    │                    ←→ maisys_drug_db (PostgreSQL)
    │                    ←→ drug-redis
    │
    ├── symptom-service  ←→ Medical RAG (Qdrant — background info only)
    │                    ←→ Infermedica API (external — Alpha mode)
    │                    ←→ vLLM server (Beta mode — fine-tuned model)
    │                    ←→ maisys_symptom_db (PostgreSQL)
    │                    ←→ symptom-redis
    │
    ├── lab-service      ←→ Medical RAG (Qdrant — enrichment)
    │                    ←→ maisys_lab_db (PostgreSQL)
    │                    ←→ lab-redis
    │
    └── research-service ←→ Paper RAG (Qdrant — per session)
                         ←→ maisys_research_db (PostgreSQL)
                         ←→ research-redis

Shared Services:
    auth-service         → maisys_auth_db
    translation-service  → translation-redis (cache only)
    export-service       → maisys_export_db
    safety-service       → stateless
    notification-service → maisys_notification_db

Infrastructure:
    model-router-service → maisys_model_router_db
    admin-service        → maisys_admin_db
    RabbitMQ             → async message broker
    vLLM server          → GPU node, serves local LLMs
```

### Database Strategy — One Database Per Service

Every service owns its own PostgreSQL database. No service queries another service's database directly. Cross-service data is accessed only via REST or RabbitMQ events. This allows each service to evolve its schema independently.

Database naming: `maisys_{service_name}_db`

### Redis Strategy — One Instance Per Service

Each module service has its own Redis instance for: response caching, session state, WebSocket pub/sub, and rate limiting counters. Shared services may share a lighter Redis instance.

---

## 3. API Gateway

### Role

Single entry point for all external traffic. No service is directly exposed. Every request from the frontend or any external client passes through the gateway, which handles routing, JWT validation, rate limiting, and request logging before forwarding to the target service.

### Routing Table

| Path Prefix | Target Service |
|---|---|
| `/api/chat/*` | chatbot-service |
| `/api/drug/*` | drug-service |
| `/api/symptom/*` | symptom-service |
| `/api/lab/*` | lab-service |
| `/api/research/*` | research-service |
| `/api/auth/*` | auth-service |
| `/api/export/*` | export-service |
| `/api/admin/*` | admin-service |
| `/ws/*` | WebSocket forwarding per service |

### Gateway Responsibilities

**Authentication verification** — gateway calls auth-service to validate JWT on all protected routes before forwarding. Invalid token → 401 response immediately, request never reaches the target service.

**Rate limiting** — per IP and per user limits enforced at gateway level. Exceeded limit → 429 response with user-friendly message, never reaches service.

**Request logging** — every request logged: method, path, status, user ID, duration, source IP.

**SSL termination** — handled at Cloudflare and/or gateway level. Internal service communication is plain HTTP within the Kubernetes cluster network.

**What the gateway does not do** — no business logic, no medical data processing, no LLM calls. Routes, validates, logs — nothing else.

---

## 4. Service Communication — REST + RabbitMQ

### Synchronous — REST

Used when the calling service needs an immediate response to continue processing.

**Examples of sync calls:**
- Any service → auth-service: validate JWT token before processing the request
- Any service → translation-service: translate text before building an LLM prompt
- Any service → safety-service: emergency check before generating any response
- Any service → model-router-service: fetch active model config for the current request

**Internal DNS:** Services reach each other using Kubernetes cluster DNS. Example: `http://auth-service/validate`, `http://translation-service/translate`. All internal calls use a short timeout (5–10 seconds maximum) and a circuit breaker. If the downstream service is unavailable, the circuit opens and the caller returns a structured error immediately.

### Asynchronous — RabbitMQ

Used for operations that do not require an immediate response and can be completed in the background.

**Examples of async messages:**
- Any service publishes to `export.request` when user requests a file export — export-service processes it and notifies when ready
- research-service publishes to `research.discovery_jobs` for paper download tasks
- symptom-service publishes to `notification.send` for session summary emails
- Any service publishes to `admin.model_usage` for metrics aggregation

**Exchange design:** Topic exchange. Each service has its own dedicated queue it consumes. Messages include: payload, source service, correlation ID, timestamp, retry count.

**Dead Letter Queue:** Failed messages after 3 retries are routed to a dead letter queue for inspection and manual replay.

### Circuit Breaker Pattern

Every inter-service REST call is wrapped in a circuit breaker. After 5 consecutive failures within 30 seconds, the circuit opens. All subsequent calls return the configured fallback immediately — no waiting for timeout. The circuit probes for recovery every 60 seconds. Failures and circuit state changes are logged and reflected in the monitoring dashboard.

---

## 5. Layered Architecture — Standard Per Service

Every service in MAISYS follows the same layered architecture. This is enforced across all services — no exceptions. Each layer has one responsibility and cannot perform another layer's duties.

### Folder Structure (Every Service)

```
service_name/
│
├── routes/                  ← HTTP layer: receive requests, validate, call service, return response
│   ├── main_routes.py       ← primary feature routes
│   └── websocket.py         ← WebSocket endpoints if needed
│
├── services/                ← Business logic: orchestrate, decide, coordinate
│   ├── main_service.py
│   └── sub_services/        ← specialized sub-service modules
│
├── repository/              ← Data access: all DB and cache queries isolated here
│   ├── postgres_repo.py     ← SQLAlchemy ORM queries
│   ├── qdrant_repo.py       ← Vector search + ingestion (for services using RAG)
│   └── cache_repo.py        ← Redis get/set/delete operations
│
├── models/                  ← Data definitions: ORM models + Pydantic schemas
│   ├── domain.py            ← SQLAlchemy ORM models (database tables)
│   └── schemas.py           ← Pydantic request/response schemas
│
├── utils/                   ← Stateless helpers: pure functions, no DB access
│   ├── text_chunker.py      ← chunking logic
│   ├── embedding_utils.py   ← embedding helpers
│   ├── file_parser.py       ← file reading utilities
│   └── export_utils.py      ← export formatting helpers
│
├── exceptions/              ← Service-specific exception classes
│   └── exceptions.py
│
├── tests/                   ← Unit + integration tests
│   ├── test_routes.py
│   ├── test_services.py
│   └── test_repository.py
│
└── main.py                  ← FastAPI app initialization, middleware, startup events
```

### Layer Rules — Never Break These

**Routes layer** — receives HTTP request, validates with Pydantic, calls one service method, returns response. Contains zero business logic. Contains zero DB access. If a route does anything beyond call-and-return, it is wrong.

**Services layer** — contains all business logic. Coordinates repositories, calls external APIs (via httpx), calls shared library functions, and calls AI services. Never contains raw SQL. Never contains ORM queries. Calls repository methods only.

**Repository layer** — all database and cache access lives here. No business logic. Takes a request from the service, executes the query or cache operation, returns the result. Services never call SQLAlchemy directly.

**Models layer** — defines ORM models (SQLAlchemy) and Pydantic schemas. No logic. No queries.

**Utils layer** — stateless pure helper functions. No database access. No service calls. Importable and testable in isolation.

**Exceptions layer** — custom exception classes specific to this service. Mapped to HTTP responses in main.py or through a global exception handler from the shared library.

### Standard API Response Format

All endpoints across all services return the same response shape:

Success: `{"success": true, "data": {...}}`
Error: `{"success": false, "error": "User-facing message"}`

Never expose in error responses: stack traces, database error messages, internal IDs, system paths, API keys.

---

## 6. Shared Library — `shared/`

The shared library is a directory at the monorepo root consumed by all services as a local Python package. It contains cross-cutting concerns that every service needs — implementing them once prevents duplication and ensures consistency.

### Shared Library Structure

```
shared/
├── auth/                    ← JWT verification utilities (used internally by services)
│   ├── jwt_handler.py       ← decode + validate JWT, extract user_id and role
│   └── dependencies.py      ← FastAPI Depends() for protected routes
│
├── chunking/                ← Medical-aware text chunker
│   ├── medical_chunker.py   ← section-aware → semantic hybrid chunker
│   ├── section_detector.py  ← detects medical section headers
│   └── token_counter.py     ← tiktoken-based token counting
│
├── concurrent/              ← Concurrency utilities
│   ├── gather_with_limit.py ← asyncio.gather with semaphore limit
│   ├── batch_processor.py   ← process list in concurrent chunks of N
│   └── progress_tracker.py  ← tracks progress across concurrent tasks
│
├── embedding/               ← Dual embedding pipeline
│   ├── minilm_embedder.py   ← all-MiniLM-L6-v2 (384-dim)
│   ├── pubmedbert_embedder.py ← PubMedBERT (768-dim)
│   ├── dual_embedder.py     ← runs both, merges and deduplicates results
│   └── similarity.py        ← cosine similarity + threshold checks
│
├── error_handler/           ← Global exception handling
│   ├── handlers.py          ← registers all exception handlers on FastAPI app
│   ├── exceptions.py        ← base exception hierarchy (all services extend from here)
│   └── responses.py         ← standardized APIResponse model
│
├── llm_client/              ← Unified LLM interface
│   ├── client.py            ← LiteLLM wrapper with retry, timeout, circuit breaker
│   ├── providers.py         ← all provider model strings + config
│   ├── kv_cache_manager.py  ← local LLM past_key_values caching
│   └── prefix_cache.py      ← cloud prompt prefix cache formatting (Anthropic + OpenAI)
│
├── logger/                  ← Structured logging
│   ├── logger.py            ← structlog setup + get_logger()
│   └── middleware.py        ← HTTP request logging middleware
│
├── models/                  ← Shared base models and types
│   ├── base.py              ← SQLAlchemy declarative base
│   ├── pagination.py        ← PaginatedResponse schema
│   └── common.py            ← shared Pydantic types used across services
│
├── progress/                ← Real-time WebSocket progress events
│   ├── publisher.py         ← publishes step events to Redis pub/sub
│   └── events.py            ← standard event types + progress percentages
│
├── rate_limiter/            ← Rate limiting
│   ├── api_limiter.py       ← slowapi limiter setup + exceeded handler
│   ├── llm_limiter.py       ← asyncio Semaphore for concurrent LLM calls
│   └── config.py            ← rate limit values per endpoint type
│
├── security/                ← File and input security
│   ├── file_validator.py    ← MIME type check + magic bytes + size limits
│   ├── filename_sanitizer.py ← safe filename normalization
│   └── input_sanitizer.py   ← sanitize user text inputs
│
└── storage/                 ← Cloud storage abstraction
    ├── storage_client.py    ← interface + factory (GCS or Azure Blob)
    ├── gcs_backend.py       ← Google Cloud Storage implementation
    └── azure_backend.py     ← Azure Blob Storage implementation
```

### How Services Use the Shared Library

Each service imports from `shared` as a local package. Example: `from shared.logger.logger import get_logger`. The shared library is mounted into each service container at build time. It is not a separate deployed service — it is code included in each service's build.

### Key Shared Modules Explained

**`shared/chunking/`** — Medical-aware chunker used by all ingestion pipelines and any service that chunks text for RAG. Implements the hybrid strategy: detect named medical section boundaries first, then apply semantic sub-chunking within sections that exceed the token limit. Preserves tables as single chunks. Tracks current section in metadata.

**`shared/concurrent/`** — Wrappers around asyncio patterns used throughout the platform. `gather_with_limit` prevents spawning thousands of coroutines simultaneously by adding a semaphore limit. `batch_processor` processes a list in concurrent chunks of configurable size — used for drug pair analysis, paper batch ingestion, and lab test explanation generation. `progress_tracker` feeds real-time progress events to the progress publisher.

**`shared/embedding/`** — Dual embedding pipeline shared by all three RAG systems. Both MiniLM and PubMedBERT run on every query. Results from both collections are merged, deduplicated by chunk ID, and sorted by score before returning top-k results to the service.

**`shared/error_handler/`** — Registers global exception handlers on every FastAPI app. Maps service-specific exceptions to correct HTTP status codes. Ensures no internal detail ever reaches the API response. Base exception hierarchy ensures every service uses the same error taxonomy.

**`shared/llm_client/`** — The single LiteLLM wrapper used by every service. Includes retry logic (exponential backoff), timeout enforcement, rate limiter integration, circuit breaker, and KV cache management. Services never call LiteLLM directly — they always go through this client.

**`shared/progress/`** — Publishes structured progress events to Redis pub/sub channel `progress:{session_id}`. WebSocket handlers in each service subscribe to this channel and forward events to the connected browser. All services use the same event types and progress percentages for consistency.

**`shared/security/`** — File validation runs on every uploaded file before any processing: MIME type check using python-magic (not just file extension), magic bytes validation, maximum file size enforcement, filename sanitization to prevent path traversal. No service processes a file before this pipeline completes.

**`shared/storage/`** — Abstraction over GCS (GCP) and Azure Blob (Azure). Switching between clouds requires only changing `CLOUD=gcp` or `CLOUD=azure` in the environment. No code changes in any service. Used by export-service (storing generated files), research-service (storing uploaded papers), lab-service (storing uploaded reports).

---

## 7. Complete Services Catalog

### 7.1 chatbot-service

**Purpose:** Conversational medical Q&A. Answers health questions using a comprehensive medical knowledge base. Supports text and voice input. Analyzes uploaded images (vision LLM) and documents (text extraction). Generates visual summaries automatically. Maintains multi-turn conversation history with sliding window memory.

**Own Database:** `maisys_chatbot_db`

**Tables:**
- `chat_sessions` — id (UUID PK), user_id, title, share_token (unique), share_expires_at, conversation_summary (TEXT), last_summarized_at, total_message_count, created_at, updated_at
- `chat_messages` — id, session_id (FK), role (user/assistant), content (TEXT), citations (JSONB), input_type (text/voice/image/file), feedback (like/dislike/null), visual_id (FK nullable), created_at
- `user_health_profiles` — id, session_id (FK), age, gender, blood_type, is_pregnant (bool), has_diabetes (bool), has_hypertension (bool), chronic_conditions (JSONB), current_medications (JSONB), allergies (JSONB), created_at, updated_at
- `chat_visuals` — id, session_id (FK), message_id (FK), visual_type (chart/infographic/diagram), diagram_subtype, title, html_content (TEXT), png_path, chart_llm_used, created_at
- `uploaded_files` — id, session_id (FK), message_id (FK), filename, file_path, file_type (pdf/docx/image), size_bytes, qdrant_indexed (bool), created_at

**RAG Access:**
- Medical RAG: Mayo Clinic (diseases, symptoms, tests, drugs) + MedlinePlus (health topics, lab tests, encyclopedia, genetics, drugs) — for general medical questions
- Drug RAG: Drugs.com general + professional PDFs — queried additionally when question involves drug information

**Layered Architecture:**
```
chatbot-service/
├── routes/
│   ├── chat_routes.py        (send message, get history, session CRUD)
│   ├── voice_routes.py       (STT + TTS)
│   ├── upload_routes.py      (image + file upload)
│   ├── visual_routes.py      (on-demand visual generation)
│   ├── profile_routes.py     (health profile)
│   ├── share_routes.py       (share link generation + access)
│   ├── action_routes.py      (like / dislike)
│   └── websocket.py          (streaming + progress)
├── services/
│   ├── chat_service.py       (main pipeline orchestrator)
│   ├── rag_service.py        (dual RAG search: medical + drug)
│   ├── enhancement_service.py (medical LLM enhancement layer)
│   ├── response_service.py   (primary LLM generation + safety wrap)
│   ├── vision_service.py     (image analysis via vision LLM)
│   ├── window_service.py     (sliding window conversation memory)
│   ├── share_service.py      (share token generation)
│   ├── profile_service.py    (health profile management)
│   ├── session_service.py    (session CRUD)
│   ├── visual/
│   │   ├── orchestrator.py   (detects triggers, selects agent)
│   │   ├── chart_agent.py    (Chart.js HTML generation)
│   │   ├── infographic_agent.py (CSS card HTML generation)
│   │   ├── diagram_agent.py  (SVG diagram generation)
│   │   └── playwright_renderer.py (HTML → PNG for exports)
│   ├── voice/
│   │   ├── stt_service.py    (speech-to-text)
│   │   ├── tts_service.py    (text-to-speech)
│   │   └── provider_selector.py
│   └── ingestion/
│       ├── pdf_ingester.py   (Drugs.com PDFs batch ingestion)
│       ├── mayo_ingester.py  (Mayo Clinic data ingestion)
│       ├── medline_ingester.py (MedlinePlus data ingestion)
│       └── file_ingester.py  (user-uploaded file → Qdrant)
├── repository/
│   ├── chat_repo.py
│   ├── qdrant_repo.py        (medical + drug collections)
│   ├── visual_repo.py
│   ├── share_repo.py
│   └── cache_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── utils/
│   ├── citation_mapper.py
│   └── prompt_builder.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

**Key Capabilities:**
- Three-LLM architecture: medical LLM (responses) + chart LLM (visuals, always cloud) + vision LLM (images/scanned files)
- Medical LLM enhancement layer: retrieved RAG chunks pass through a medical LLM that refines and validates the context before the primary LLM generates the final response
- Sliding window conversation memory: last 10 messages in full + rolling summary of older messages, updated every 5 new messages, maximum 2000 history tokens
- User health profile injection: age, gender, pregnancy status, chronic conditions injected into system prompt for context-aware responses
- Share URL: generates a unique token with configurable expiry; shared sessions are read-only

**RabbitMQ:**
- Publishes to `export.request`, `admin.model_usage`
- Consumes from `chatbot.ingestion_jobs`

---

### 7.2 drug-service

**Purpose:** Comprehensive drug information hub. Handles 12 drug features. Uses a two-tier retrieval system: Drug RAG first, Drugs.com web agent as fallback when RAG is insufficient.

**Own Database:** `maisys_drug_db`

**Tables:**
- `drug_sessions` — id (UUID PK), user_id, feature (VARCHAR), input_drugs (JSONB), result (JSONB), source_tier (local/web), web_sources (JSONB), created_at
- `export_history` — id, session_id (FK), format, created_at
- `model_usage_log` — id, session_id (FK), model_used, feature, tokens_approx, duration_ms, created_at

**RAG Access — Drug RAG (comprehensive drug data):**
The Drug RAG knowledge base contains drug information from four sources, all section-filtered:
- Drugs.com general PDFs (17,432 drugs — patient-facing information)
- Drugs.com professional PDFs (6,450+ drugs — prescribing information, package inserts, pharmacokinetics)
- Mayo Clinic drugs section (from part4_drugs scraper — drug descriptions, usage, precautions, side effects)
- MedlinePlus drugs section (from part2_drugs scraper — consumer drug information, brand/generic mappings)

All four sources are ingested into the same Qdrant collections (`minilm_drugs`, `pubmedbert_drugs`) with metadata distinguishing source type. Section-level filtering (DOSAGE, DRUG INTERACTIONS, PHARMACOKINETICS, CONTRAINDICATIONS, etc.) applies to all sources.

**Two-Tier Retrieval:**
- Tier 1: Drug RAG search with section filter
- Tier 2 (fallback when RAG insufficient): Web search agent — navigates Drugs.com live for drug-drug interactions; SerpAPI web search for all other features
- Sufficiency threshold: minimum 3 relevant chunks AND LLM confidence ≥ 0.75

**Drugs.com Interaction Agent — Exact Flow:**
When RAG is insufficient for a drug-drug interaction request, the web search agent executes the following steps using Playwright (headless Chromium):

Step 1 — Navigate to `https://www.drugs.com/drug_interactions.html`
Step 2 — For each drug name in the user's request: type the name into the interaction checker input field, wait for the autocomplete suggestion to appear, select or confirm the drug
Step 3 — After all drug names are entered, click the "Check Interactions" button
Step 4 — Wait for the results page to fully load — specifically wait for the interaction results panel to appear in the DOM
Step 5 — Render the full results page and extract content using BeautifulSoup: for each interaction pair found, extract severity level, drug pair names, interaction description, clinical significance, and recommendation
Step 6 — Pass the extracted structured text to the medical LLM, which formats it into the standard MAISYS drug interaction response with proper severity labels and a citation pointing to `https://www.drugs.com/drug_interactions.html` as the source

This flow reuses the same Playwright setup, DOM selectors, and BeautifulSoup extraction approach already implemented in `drugs_com_scraper.py` in the codebase. The agent activates this flow on demand when RAG is insufficient, rather than as a batch scraping job.

**Drug Data Acquisition Agent (LangGraph):**
When a user queries a drug that returns zero or near-zero RAG results, this agent activates asynchronously. It searches Drugs.com, scrapes the drug page, extracts content (PyMuPDF + pdfplumber), chunks and embeds it, and upserts it into Qdrant — making it available for all future queries. It also notifies the failed-drug retry pipeline to add the URL for re-scraping the full PDF.

**Failed PDF Retry Script (not agent):**
A standalone Python script in `ingestion/retry_failed_drugs.py`. Reads the 42 failed URLs from the original scraping run. Retries each URL: attempt 1 with different User-Agent, attempt 2 with extended delay, attempt 3 with fresh browser context, attempt 4 with /pro/ URL variant. Logs all outcomes and flags remaining failures for manual review.

**12 Features:**
Drug profile lookup, brand/generic conversion, drug class browser, drug-drug interaction checking, drug-food interaction checking, drug-disease contraindication checking, pregnancy safety checking, dosage calculator (adult + weight-based pediatric + renal + hepatic adjustment), drug alternative finder, drug comparison, pharmacokinetics viewer, off-label use explorer.

**Layered Architecture:**
```
drug-service/
├── routes/
│   ├── drug_info_routes.py   (lookup, brand/generic, class browser)
│   ├── interaction_routes.py (drug-drug, food, disease, pregnancy)
│   ├── practical_routes.py   (dosage, alternatives)
│   ├── clinical_routes.py    (comparison, PK, off-label)
│   └── websocket.py
├── services/
│   ├── retrieval_router.py   (Tier 1 → sufficiency → Tier 2)
│   ├── sufficiency_evaluator.py
│   ├── normalization_service.py (RxNorm + scispaCy fallback)
│   ├── drug_info_service.py
│   ├── interaction_service.py
│   ├── practical_service.py
│   ├── clinical_service.py
│   ├── visual/               (same 3 visual agents as chatbot)
│   └── voice/                (same STT/TTS as chatbot)
├── agents/
│   ├── orchestrator.py       (LangGraph — selects agent per feature)
│   ├── drug_lookup_agent.py
│   ├── interaction_agent.py
│   ├── dosage_agent.py
│   ├── comparison_agent.py
│   ├── pharmacokinetics_agent.py
│   ├── alternative_agent.py
│   ├── web_search_agent.py   (Drugs.com live fallback)
│   └── drug_acquisition_agent.py (new drugs not in RAG)
├── scripts/
│   └── drugs_com_scraper.py  (Playwright interaction scraper — called by web_search_agent)
├── repository/
│   ├── drug_repo.py
│   ├── qdrant_repo.py        (drug collections only)
│   └── cache_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── utils/
│   ├── rxnorm_client.py
│   └── drug_pair_generator.py
├── exceptions/
│   └── exceptions.py
├── ingestion/
│   ├── ingest_drugs_pdfs.py  (Drugs.com general + professional)
│   ├── ingest_mayo_drugs.py  (Mayo Clinic part4 drugs)
│   ├── ingest_medlineplus_drugs.py (MedlinePlus part2 drugs)
│   ├── retry_failed_drugs.py
│   └── run_drug_ingestion.py (master runner)
├── tests/
└── main.py
```

**RabbitMQ:**
- Publishes to `export.request`, `admin.model_usage`, `drug.acquisition_jobs`
- Consumes from `drug.acquisition_jobs` (processes async drug acquisition tasks)

---

### 7.3 symptom-service

**Purpose:** Conversational symptom assessment in two modes. Alpha (production): Infermedica handles all medical reasoning; LLM handles all language. Beta (experimental): fine-tuned LLM — available only to triple-consented users.

**Own Database:** `maisys_symptom_db`

**Tables:**
- `symptom_sessions` — id (UUID — used as Interview-Id), user_id, mode (alpha/beta), age, sex, language, chief_complaint, evidence (JSONB), turns (INT), created_at
- `symptom_results` — id, session_id (FK), conditions (JSONB), triage_level, explanation (TEXT), triage_summary (TEXT), background_info (TEXT), created_at
- `export_history` — id, session_id (FK), format, created_at
- `beta_consents` — user_id (PK), gate_1_consent, gate_1_timestamp, gate_2_consent, gate_2_timestamp, gate_3_consent, gate_3_timestamp, withdrawn_at
- `beta_sessions` — id, user_id_hash (hashed — not direct link), age, sex, chief_complaint, beta_response, consent_version, created_at
- `beta_review_queue` — id, source_type, unified_record (JSONB), gp_reviewed (bool), gp_reviewer_id, gp_label, gp_notes, approved_for_training (bool), reviewed_at
- `beta_training_runs` — id, dataset_size, base_model, triage_accuracy, condition_accuracy, deployed (bool), run_at

**RAG Access (Alpha):** Medical RAG — after Infermedica returns the final conditions and triage level, the service queries Medical RAG for background information about the top conditions (what the condition is, typical symptoms, what to expect). This enrichment is shown alongside Infermedica results as educational context. It does not influence Infermedica's reasoning.

**Alpha LLM Tasks:** Rephrase Infermedica's clinical questions into natural friendly language. Parse user's free-text answers into present/absent/unknown choices. Explain top conditions in plain language after Infermedica returns results. Generate triage summary with next-step guidance.

**Beta mode:** Fine-tuned medical LLM served via vLLM. Triple consent gates enforced before any Beta session begins (explicit consent screen + account settings opt-in + onboarding flow). All Beta sessions anonymized before storage.

**Layered Architecture:**
```
symptom-service/
├── routes/
│   ├── alpha_routes.py       (start session, submit answer, get results)
│   ├── beta_routes.py        (Beta session endpoints — consent enforced)
│   ├── consent_routes.py     (save consent gate status)
│   └── websocket.py
├── services/
│   ├── session_service.py    (Alpha: orchestrates full Infermedica + LLM flow)
│   ├── infermedica_service.py (all 5 Infermedica endpoint wrappers)
│   ├── llm_service.py        (4 LLM prompt tasks)
│   ├── triage_service.py     (triage level → color + action + summary)
│   ├── beta_session_service.py
│   ├── consent_service.py
│   ├── translation_client.py (calls translation-service)
│   ├── visual/
│   └── voice/
├── infermedica/
│   ├── client.py             (base httpx client with App-Id, App-Key, Interview-Id headers)
│   ├── parse.py              (/parse endpoint)
│   ├── diagnosis.py          (/diagnosis endpoint)
│   ├── triage.py             (/triage endpoint)
│   ├── conditions.py         (/conditions/{id} endpoint)
│   └── symptoms.py           (/symptoms search endpoint)
├── repository/
│   ├── session_repo.py
│   ├── beta_repo.py
│   ├── qdrant_repo.py        (medical RAG — background enrichment only)
│   └── cache_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── utils/
│   └── stop_condition.py     (evaluates all 4 stop conditions)
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

**Stop Conditions (any one triggers finalization):**
1. Infermedica returns `should_stop: true`
2. Turn limit reached (maximum 8 turns)
3. Top condition probability ≥ 0.85 (confident result)
4. Probability gap between top and second condition ≥ 0.5 (clear winner)

**RabbitMQ:**
- Publishes to `export.request`, `admin.model_usage`, `symptom.beta_session` (anonymized for review queue)

---

### 7.4 lab-service

**Purpose:** Lab test report analysis. Accepts uploaded reports as digital PDFs, scanned PDFs, or images. Extracts test values, generates per-test explanations, produces visual summaries, and provides a follow-up chat workspace.

**Own Database:** `maisys_lab_db`

**Tables:**
- `lab_sessions` — id (UUID PK), user_id, filename, file_type, file_path, status (processing/complete/error), created_at
- `lab_tests` — id, session_id (FK), test_name, value, unit, reference_range, status (normal/high/low/critical), section (panel name), created_at
- `lab_explanations` — id, lab_test_id (FK), explanation (TEXT), urgency_level, created_at
- `lab_summaries` — id, session_id (FK), summary_text (TEXT), urgency_level (none/routine/soon/urgent), normal_count, abnormal_count, created_at
- `lab_visuals` — id, session_id (FK), visual_type, html_content (TEXT), png_path, created_at
- `lab_chat_messages` — id, session_id (FK), role, content (TEXT), citations (JSONB), input_type, feedback, created_at

**RAG Access — Enrichment Only:**
The lab-service primarily relies on the medical LLM's trained knowledge to understand lab tests, their meanings, and normal ranges. The LLM generates explanations directly from the extracted test data and its domain knowledge.

Medical RAG is additionally queried for each identified test to retrieve specific MedlinePlus lab test pages and Mayo Clinic test descriptions. If RAG returns relevant results, they are injected as additional context into the LLM prompt to enrich the explanation. If RAG returns no results for a test, the LLM proceeds with its own knowledge — no failure, no fallback needed. The LLM is the primary knowledge source; RAG is the enrichment layer.

**Vision LLM for Image Uploads:**
When the uploaded file is an image (JPG, PNG, WEBP) or a scanned PDF (image pages), the vision LLM analyzes the image to extract text content before the parsing pipeline runs. The vision model returns a structured text extraction that feeds into the parsing stage. This path is used when:
- File extension is JPG, PNG, or WEBP
- PDF is detected as image-based (no selectable text)

**Hybrid Parsing Pipeline:**
Stage 1 (rule-based): regex patterns + scispaCy medical NER scan raw text for test names, values, units, reference ranges.
Stage 2 (LLM validation): medical LLM receives raw text + Stage 1 candidates and returns validated structured JSON array with test_name, value, unit, reference_range, status, section fields.

**Concurrent Explanation Generation:**
All per-test explanations are generated concurrently using asyncio.gather with a semaphore limit. Typical lab reports have 10–40 tests — parallel generation reduces total processing time from minutes to seconds.

**Layered Architecture:**
```
lab-service/
├── routes/
│   ├── upload_routes.py      (upload lab report)
│   ├── result_routes.py      (get structured results)
│   ├── chat_routes.py        (follow-up chat)
│   ├── visual_routes.py      (on-demand diagram)
│   └── websocket.py
├── services/
│   ├── upload_service.py     (file validation + routing to correct pipeline)
│   ├── extraction_service.py (PDF text extraction + scanned PDF detection)
│   ├── vision_service.py     (image/scanned PDF → vision LLM)
│   ├── parsing_service.py    (hybrid: rule-based + LLM validation)
│   ├── explanation_service.py (concurrent per-test LLM explanation)
│   ├── summary_service.py    (overall report summary + urgency)
│   ├── chat_service.py       (follow-up chat with lab context)
│   └── visual/               (chart + infographic + diagram agents)
│   └── voice/
├── ocr/
│   ├── engine_selector.py    (selects OCR engine including LLM-based)
│   ├── paddle_wrapper.py
│   ├── mistral_wrapper.py
│   ├── lighton_wrapper.py
│   └── llm_ocr_wrapper.py    (vision LLM as OCR engine for complex layouts)
├── nlp/
│   └── scispacy_parser.py    (Stage 1 rule-based parsing)
├── repository/
│   ├── lab_repo.py
│   ├── qdrant_repo.py        (medical RAG enrichment queries)
│   └── cache_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── utils/
│   └── pdf_detector.py       (detects digital vs scanned PDF)
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

**RabbitMQ:**
- Publishes to `export.request`, `admin.model_usage`

---

### 7.5 research-service

**Purpose:** Research paper discovery, analysis, and deep exploration. Upload papers directly or discover them via AI-powered search. Each session has its own per-session RAG workspace for grounded paper chat.

**Own Database:** `maisys_research_db`

**Tables:**
- `research_sessions` — id (UUID PK), user_id, title, share_token (unique), share_expires_at, created_at, updated_at
- `papers` — id, session_id (FK), title, authors (JSONB), doi, year, abstract, file_path, source (upload/semantic_scholar), qdrant_collection_id, extracted_text (TEXT), status, created_at
- `paper_chat_messages` — id, session_id (FK), paper_ids (JSONB), role, content, citations (JSONB), input_type, feedback, created_at
- `paper_summaries` — id, paper_id (FK), summary_type, content, mode_used (model/llm), language, created_at
- `paper_translations` — id, paper_id (FK), source_language, target_language, translated_content, mode_used, created_at
- `paper_qa_sets` — id, paper_id (FK), qa_pairs (JSONB), mode_used, created_at
- `paper_comparisons` — id, session_id (FK), paper_ids (JSONB), comparison_table (JSONB), narrative, created_at
- `paper_visuals` — id, session_id (FK), paper_ids (JSONB), visual_type, html_content, png_path, created_at
- `discovery_jobs` — id, session_id (FK), query, status (queued/running/complete/error), results (JSONB), created_at

**RAG Access:** Per-session Paper RAG. Each session gets its own Qdrant collection named `papers_{session_id}`. Destroyed when session is deleted. The paper's extracted text is chunked, embedded (dual embedding), and indexed into this collection on upload or after discovery download.

**Paper Discovery Agent (LangGraph):**
Activated when user describes their research topic. The agent runs as a background job via RabbitMQ. The user receives WebSocket progress events throughout the entire process.

The agent pipeline has two search strategies working in sequence:

**Strategy 1 — Semantic Scholar API:** Extracts precise keywords from the user's description using the LLM, queries the Semantic Scholar API, retrieves paper metadata (title, authors, abstract, DOI, year, open-access PDF link if available), ranks results by relevance.

**Strategy 2 — Broader Web Search (fallback or supplement):** If Semantic Scholar returns few results or the user's topic is niche, the agent additionally runs a web search using SerpAPI to find papers on Google Scholar, PubMed, arXiv, and other academic sources. This expands coverage beyond Semantic Scholar's index.

**For each paper found — download attempt:**
The agent attempts to download the PDF directly. Download succeeds when the paper is open-access or the PDF link is freely available.

If download succeeds: the paper is ingested immediately (OCR if needed → chunk → embed → Qdrant session collection → PostgreSQL). Progress event shows which paper is being processed.

If download fails (paywalled, no direct PDF link, access restricted, download error): the agent does NOT skip the paper. Instead, it adds the paper to a "Pending Upload" list with its complete metadata: full title, authors, abstract, DOI, journal, year, and the URL where the paper can be found (publisher page, DOI link, or ResearchGate/Academia page if found). After the discovery job completes, the final report distinguishes between "Added to your workspace" and "Requires manual download". For papers requiring manual download, the UI shows each paper's information with its link and a dedicated upload button. The user can visit the link, download the PDF, and upload it directly to that paper's slot in the session. Once uploaded, the app processes it automatically and adds it to the RAG workspace.

**Discovery Report (final output):**
- Total papers found
- Papers successfully added to workspace (with titles)
- Papers pending manual download (with titles, abstract snippets, links)
- Papers that failed entirely (if any)

The user can work with the successfully downloaded papers immediately while they manually retrieve the others in parallel.

**Specialized NLP Tools (Model Mode vs LLM Mode):**
See Section 9 for full description. Research-service implements all four: Summarization, Q&A Generation, Translation EN↔AR, all with configurable mode (local ML model or cloud/local LLM via LiteLLM).

**Vision LLM:**
When a paper contains scanned pages or embedded figures that cannot be extracted as text, the vision LLM analyzes those pages and returns text content, enabling analysis of older scanned academic papers and extraction of insight from visual data within papers.

**Share URL:** Research sessions can be shared via a unique token with configurable expiry. Shared sessions are read-only for recipients.

**Layered Architecture:**
```
research-service/
├── routes/
│   ├── session_routes.py     (session CRUD)
│   ├── paper_routes.py       (upload, discover, list)
│   ├── chat_routes.py        (paper chat)
│   ├── tool_routes.py        (summarize, translate, QA, compare)
│   ├── share_routes.py       (share link)
│   ├── visual_routes.py
│   └── websocket.py
├── services/
│   ├── session_service.py
│   ├── paper_service.py      (upload handling + ingestion trigger)
│   ├── chat_service.py       (RAG chat grounded in paper content)
│   ├── summarization_service.py (model mode: DistilBART / llm mode: LiteLLM)
│   ├── translation_service.py (model mode: opus-mt / llm mode: LiteLLM)
│   ├── qa_service.py         (model mode: T5-small / llm mode: LiteLLM)
│   ├── comparison_service.py (multi-paper comparison via concurrent RAG)
│   ├── share_service.py
│   ├── vision_service.py     (scanned pages + figure analysis)
│   ├── visual/
│   └── voice/
├── agents/
│   └── paper_discovery_agent.py (LangGraph: keyword→search→download→ingest→report)
├── nlp_models/
│   ├── distilbart_summarizer.py  (local model mode)
│   ├── t5_qa_generator.py        (local model mode)
│   ├── opus_mt_translator.py     (local model mode)
│   └── mode_selector.py          (routes to model or LLM based on config)
├── ocr/
│   ├── engine_selector.py
│   ├── paddle_wrapper.py
│   ├── mistral_wrapper.py
│   ├── lighton_wrapper.py
│   └── llm_ocr_wrapper.py
├── ingestion/
│   └── paper_ingester.py     (extract → chunk → embed → Qdrant session collection)
├── repository/
│   ├── session_repo.py
│   ├── paper_repo.py
│   ├── qdrant_repo.py        (per-session collections)
│   └── cache_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── utils/
│   ├── semantic_scholar_client.py
│   └── citation_formatter.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

**Concurrent and Batch Processing (from paper guide patterns):**
- Multiple paper uploads processed concurrently: asyncio.gather with semaphore limit
- OCR on large PDFs: pages split into chunks of 10, processed in parallel, results merged in order
- Simultaneous NLP tools: summarization + translation + QA generation run concurrently when all three are requested
- Batch ingestion of discovered papers: processed in concurrent chunks of 10, progress reported after each chunk

**RabbitMQ:**
- Publishes to `export.request`, `research.discovery_jobs`, `admin.model_usage`
- Consumes from `research.discovery_jobs` (background paper processing)

---

### 7.6 auth-service

**Purpose:** All authentication and authorization. Issues JWTs, manages refresh tokens, OTP, Google and Apple OAuth, email verification, password reset.

**Own Database:** `maisys_auth_db`

**Tables:**
- `users` — id (UUID PK), email (unique), password_hash, role (user/beta_user/gp_reviewer/admin), email_verified (bool), created_at, updated_at
- `refresh_tokens` — id, user_id (FK), token_hash, expires_at, revoked (bool), created_at
- `otp_codes` — id, user_id (FK), code_hash, purpose (email_verify/password_reset/login_otp), expires_at, used (bool), created_at
- `oauth_accounts` — id, user_id (FK), provider (google/apple), provider_user_id, created_at
- `sessions` — id, user_id (FK), jwt_jti (unique), issued_at, expires_at, revoked (bool)

**JWT Configuration:** HS256 algorithm, 24-hour access token expiry, 7-day refresh token expiry with rotation on use.

**Roles:** user (standard), beta_user (triple-consented + Beta access), gp_reviewer (admin panel Beta review queue), admin (full admin panel).

**Layered Architecture:**
```
auth-service/
├── routes/
│   └── auth_routes.py        (register, login, logout, refresh, verify, OAuth, OTP, validate)
├── services/
│   ├── auth_service.py
│   ├── otp_service.py
│   └── oauth_service.py
├── repository/
│   └── user_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

### 7.7 translation-service

**Purpose:** Arabic ↔ English translation for all services. Stateless with Redis cache. Supports three translation methods.

**Translation Methods:**
- Google Translate API (primary cloud, strong Arabic support)
- deep-translator library (local fallback, no API key required, good for general text)
- LLM-based translation via LiteLLM (for medical terminology requiring context-awareness — when standard translation may distort clinical meaning)

The translation method is configurable per request: `mode=google`, `mode=local`, or `mode=llm`. Default is Google. LLM mode is recommended for medical terminology, drug names with Arabic equivalents, and clinical explanations.

**Caching:** Translation results cached in Redis for 24 hours, keyed by SHA-256 hash of source text + language pair. Cache is the first check on every translation request.

**Layered Architecture:**
```
translation-service/
├── routes/
│   └── translation_routes.py
├── services/
│   ├── translation_service.py
│   ├── lang_detector.py
│   └── mode_selector.py
├── repository/
│   └── cache_repo.py
├── models/
│   └── schemas.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

### 7.8 export-service

**Purpose:** Generates TXT, DOCX, and PDF exports for all services asynchronously via RabbitMQ.

**Own Database:** `maisys_export_db`

**Tables:**
- `export_jobs` — id (UUID PK), source_service, session_id, format, status (queued/processing/complete/error), file_path, requested_by, created_at, completed_at
- `export_files` — id, job_id (FK), file_path, file_size_bytes, expires_at, created_at

**Export Formats:**
- TXT: plain text with section headers, UTF-8, section dividers
- DOCX: formatted headers, tables, bold, Arabic RTL support (python-docx), Noto Sans Arabic font
- PDF: professional layout, Arabic RTL, triage color badges, tables, Noto Sans Arabic font (fpdf2/reportlab)

All exports include: source tier label (local knowledge base / web source), full citations with URLs, medical disclaimer footer, service name and generation timestamp.

**Layered Architecture:**
```
export-service/
├── routes/
│   └── export_routes.py      (status check, download)
├── services/
│   ├── export_service.py     (consumes RabbitMQ queue, dispatches to generators)
│   └── generators/
│       ├── txt_generator.py
│       ├── docx_generator.py
│       └── pdf_generator.py
├── repository/
│   └── export_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── fonts/
│   └── NotoSansArabic.ttf
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

### 7.9 safety-service

**Purpose:** Emergency detection and disclaimer injection. Stateless. Called by every module service before processing any user input.

**Emergency Detection:** Scans input in both Arabic and English for emergency patterns (chest pain, difficulty breathing, unconsciousness, severe bleeding, overdose, seizure, cardiac arrest, stroke, allergic reaction, and Arabic equivalents). If detected, returns an emergency response object — the calling service halts normal processing and presents the emergency alert.

**Profile-Aware Warnings:** When a user health profile contains pregnancy status or relevant chronic conditions, the safety service injects additional warnings into responses from any service.

**Standard Disclaimer:** Appended to all responses from all services: not a diagnosis, not a prescription, always consult a qualified healthcare professional.

**Layered Architecture:**
```
safety-service/
├── routes/
│   └── safety_routes.py      (check, wrap)
├── services/
│   ├── emergency_detector.py
│   └── disclaimer_injector.py
├── models/
│   └── schemas.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

### 7.10 notification-service

**Purpose:** Sends all outbound notifications — OTP emails, email verification, password reset, export-ready alerts.

**Own Database:** `maisys_notification_db`

**Tables:**
- `notification_log` — id, user_id, type, recipient_email, status (sent/failed), sent_at, error_detail

**Email Provider:** SendGrid (primary) or SMTP (fallback). Provider configurable via environment.

**Layered Architecture:**
```
notification-service/
├── routes/
│   └── notification_routes.py (status query)
├── services/
│   ├── email_service.py
│   └── provider_selector.py
├── repository/
│   └── notification_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

### 7.11 model-router-service

**Purpose:** Central LLM configuration and admin model management. Module services query this service before every LLM call to get the currently active model. Admin switches models from the dashboard — changes take effect immediately.

**Own Database:** `maisys_model_router_db`

**Tables:**
- `model_registry` — id, model_name, provider, model_string (LiteLLM format), role (medical/chart/vision/stt/tts/embedding/ocr), is_local (bool), cost_per_1k_tokens, latency_sla_ms, is_available (bool), notes
- `active_model_config` — id, service_name, llm_role, model_registry_id (FK), switched_at, switched_by
- `model_usage_metrics` — id, service_name, model_registry_id (FK), request_count, avg_latency_ms, error_count, total_tokens, recorded_at

**Layered Architecture:**
```
model-router-service/
├── routes/
│   └── model_routes.py       (config get, switch, registry list, metrics)
├── services/
│   ├── config_service.py
│   └── metrics_service.py
├── repository/
│   └── model_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

### 7.12 admin-service

**Purpose:** Admin panel backend. GP review queue for Beta symptom checker, user management, system monitoring, model performance tracking.

**Own Database:** `maisys_admin_db`

**Tables:**
- `admin_users` — id, email, password_hash, role (gp_reviewer/system_admin), created_at
- `audit_log` — id, admin_user_id, action, target_resource, details (JSONB), created_at

**Layered Architecture:**
```
admin-service/
├── routes/
│   ├── admin_auth_routes.py  (separate admin login)
│   ├── review_routes.py      (Beta GP review queue)
│   ├── user_routes.py        (user management)
│   └── monitoring_routes.py  (metrics + model tracker)
├── services/
│   ├── review_service.py
│   ├── user_admin_service.py
│   └── monitoring_service.py
├── repository/
│   └── admin_repo.py
├── models/
│   ├── domain.py
│   └── schemas.py
├── exceptions/
│   └── exceptions.py
├── tests/
└── main.py
```

---

## 8. Shared Capabilities Across All Services

### Visual Agents — All Services (Auto-Trigger Only)

The three visual agents (Chart Agent, Infographic Agent, Diagram Agent) are a shared library module available to all five module services. They are not a separate microservice — they run in-process within each service that uses them.

**Chart Agent:** Generates Chart.js HTML/JS charts — bar charts, line charts, radar charts. Triggered by numerical comparisons, ranges, statistics, or values that are better understood visually. Examples: drug dosage comparison table, lab values vs reference ranges across tests, drug interaction severity distribution.

**Infographic Agent:** Generates CSS card HTML. Triggered by structured key facts, summaries, or categorical information. Examples: per-test lab result summary cards, drug profile overview cards, condition overview cards.

**Diagram Agent:** Generates SVG medical diagrams. Triggered by spatial or structural relationships. Examples: body system diagrams, drug mechanism of action diagrams, symptom-to-condition relationship flows, medical timelines.

**Visual Orchestrator:** After the main LLM response is generated, the orchestrator applies rule-based detection on the response content. If a visual trigger is detected (numeric data, comparison tables, lists of conditions, ranges), the orchestrator selects the appropriate agent and generates the visual. This happens automatically — there is no user-facing button. The chart LLM (always cloud) generates the HTML/JS/CSS. Playwright renders the HTML to PNG for inclusion in exports.

### STT / TTS — All Services

All five module services support voice input and voice output. STT transcribes voice recordings to text before the processing pipeline. TTS converts response text to audio for playback.

**STT Providers:** Faster Whisper (local), ElevenLabs, Google Gemini, Supertone/supertonic-3
**TTS Providers:** Edge-TTS (local), ElevenLabs, Google Gemini

Active provider per service configurable via model-router-service.

### Export — All Services

All services generate TXT, DOCX, and PDF exports via the shared export-service asynchronously. Export includes source labels, citations, and disclaimers.

---

## 9. Specialized NLP Tools — Model Mode vs LLM Mode

Some services (research-service, lab-service) offer NLP operations in two configurable modes. This allows the system to use lightweight local ML models for efficiency, or full LLMs via LiteLLM for higher quality — switchable per service without code changes.

### Tool Catalog

| Tool | Model Mode (local ML) | LLM Mode (via LiteLLM) | Export |
|---|---|---|---|
| **Summarization** | `distilbart-cnn-12-6` (sshleifer) | Any LiteLLM provider | TXT, DOCX, PDF |
| **Q&A Generation** | `t5-small` (Google) | Any LiteLLM provider | TXT, DOCX, PDF |
| **Translation EN→AR** | `opus-mt-en-ar` (Helsinki-NLP) | Any LiteLLM provider | TXT, DOCX, PDF |
| **Translation AR→EN** | `opus-mt-ar-en` (Helsinki-NLP) | Any LiteLLM provider | TXT, DOCX, PDF |
| **Translation (multilingual alt)** | `nllb-200-distilled-600M` (Facebook) | Any LiteLLM provider | TXT, DOCX, PDF |
| **OCR** | PaddleOCR / Mistral / LightOn / LLM-based | — | TXT, DOCX, PDF |

### Mode Selection

Mode is configured per tool per service in the environment or via model-router-service. When `SUMMARIZATION_MODE=model`, the local DistilBART model runs. When `SUMMARIZATION_MODE=llm`, LiteLLM is called with the active provider. The service routes to the correct implementation transparently — the route layer and repository layer are unaware of which mode is active.

### When to Use Each Mode

**Model Mode:** Lower cost, no API dependency, faster for batch jobs, sufficient for straightforward summarization and translation tasks. Suitable when GPU or CPU resources are available locally.

**LLM Mode:** Higher quality output, context-aware translation (critical for medical terminology), better handling of complex or ambiguous text, better Arabic accuracy. Required for high-stakes explanations.

---

## 10. OCR Engines — Including LLM-Based OCR

All services that process uploaded documents (lab-service, research-service, chatbot-service) use the same OCR pipeline with four available engines. The engine is selectable via configuration.

### Engine 1 — PaddleOCR (Local)

Type: Local model, no API key, fully offline.
Best for: Standard printed text, general lab documents, most common formats.
Supported: PNG, JPG, JPEG, TIFF, BMP, scanned PDF pages.
Limitation: Complex layouts, non-standard fonts, or heavily compressed scans may yield lower accuracy.

### Engine 2 — Mistral OCR API (Cloud)

Type: Cloud API, requires `MISTRAL_API_KEY`.
Best for: Complex and dense document layouts, mixed content, tables within PDFs.
High accuracy on documents with complex structure.
Limitation: API cost per call, network dependency.

### Engine 3 — LightOnOCR (Cloud)

Type: Cloud API, requires `LIGHTON_API_KEY`.
Best for: Scientific and academic documents, medical reports with specialized formatting.
Specifically optimized for research papers and medical content.
Limitation: API cost, network dependency.

### Engine 4 — LLM-Based OCR (Vision LLM)

Type: Cloud or local vision LLM (GPT-4o Vision, Gemini Vision, Claude Vision, LLaVA, Gemma 4).
How it works: The scanned page or image is sent to the vision LLM with a prompt asking it to transcribe all text content accurately, preserve formatting where possible, and note any tables or structured data.
Best for: Handwritten lab reports, prescriptions, highly complex mixed layouts, images where traditional OCR consistently fails, or when semantic understanding of the image content is needed alongside text extraction.
Limitation: Higher cost per call than traditional OCR, slower, token limits apply to very large documents.

**Engine Selection Logic:**
The engine selector applies this priority order unless overridden by configuration:
1. If document is a standard digital PDF → direct text extraction (no OCR needed)
2. If document is a scanned PDF or image → try configured primary OCR engine
3. If primary engine fails or returns empty result → fallback to next engine in chain
4. Chain: PaddleOCR → Mistral → LightOn → LLM-based OCR
5. If all engines fail → return structured error with partial text if available

Admin configures the primary engine and fallback chain via model-router-service.

---

## 11. Model Registry and Admin Model Switcher

### What It Does

The model-router-service maintains the active AI model configuration for every service and every AI role. Before every LLM, STT, TTS, or OCR call, the service fetches the current active config from the model-router-service. The admin switches models from the admin dashboard — the change takes effect immediately on the next request. No service restart required.

Users see only the response. Which model generated it is invisible to them.

### Traffic-Based Switching Scenario

High traffic causes OpenAI API costs to spike. Admin opens the model dashboard, sees real-time cost and latency metrics per service, and switches chatbot-service's medical LLM from `gpt-4o` to `biogpt` (local via vLLM). The switch is instant. The next chatbot request fetches the updated config and uses BioGPT. Costs drop immediately.

Reverse scenario: vLLM GPU is overloaded. Admin switches all services from local LLMs back to cloud providers in seconds.

### Circuit Breaker — Automatic Fallback

If the active cloud LLM fails 5 consecutive times within 30 seconds, the circuit opens. The service automatically falls back to the configured local fallback model via vLLM. The circuit probes for recovery every 60 seconds. Admin receives an alert on the monitoring dashboard. When the cloud provider recovers, admin can manually close the circuit and resume cloud routing.

### Model Roles

| Role | Purpose | Available To |
|---|---|---|
| medical LLM | Response generation, RAG context enhancement, lab explanation | All module services |
| chart LLM | Visual generation (Chart/Infographic/Diagram agents) — always cloud | All module services |
| vision LLM | Image understanding, scanned document analysis | chatbot, lab, research |
| STT | Voice input transcription | All module services |
| TTS | Voice response playback | All module services |
| embedding | Chunk embedding for RAG (ingestion + query) | All services with RAG |
| OCR primary | Primary OCR engine selection | lab, research, chatbot |

---

## 12. Complete Model Catalog

### 12.1 Cloud LLMs (via LiteLLM)

| Provider | Model | LiteLLM String | Prefix Cache |
|---|---|---|---|
| OpenAI | GPT-4o | `gpt-4o` | Auto (>1024 tokens, 50% cost) |
| OpenAI | GPT-4o mini | `gpt-4o-mini` | Auto (>1024 tokens, 50% cost) |
| OpenAI | GPT-3.5 Turbo | `gpt-3.5-turbo` | No |
| Anthropic | Claude 3.5 Sonnet | `anthropic/claude-3-5-sonnet-20241022` | Explicit marker (25% cost) |
| Anthropic | Claude 3 Haiku | `anthropic/claude-3-haiku-20240307` | Explicit marker (25% cost) |
| Google | Gemini 1.5 Pro | `gemini/gemini-1.5-pro` | No |
| Google | Gemini 1.5 Flash | `gemini/gemini-1.5-flash` | No |
| Groq | LLaMA 3.1 70B | `groq/llama-3.1-70b-versatile` | No |
| Groq | LLaMA 3.1 8B | `groq/llama-3.1-8b-instant` | No |
| Groq | LLaMA 3 70B | `groq/llama3-70b-8192` | No |
| Groq | LLaMA 3 8B | `groq/llama3-8b-8192` | No |
| Mistral | Mistral Large | `mistral/mistral-large-latest` | No |
| Mistral | Mistral Small | `mistral/mistral-small-latest` | No |
| Cohere | Command R+ | `cohere/command-r-plus` | No |
| Cohere | Command R | `cohere/command-r` | No |
| Azure OpenAI | GPT-4o (Azure) | `azure/gpt-4o` | Auto |

### 12.2 Local Medical LLMs (HuggingFace Transformers + vLLM)

| Model | HuggingFace ID | Size | Domain | Quantization |
|---|---|---|---|---|
| BioGPT | `microsoft/biogpt` | 347M | PubMed biomedical text | 8-bit supported |
| BioMedLM | `stanford-crfm/BioMedLM` | 2.7B | Biomedical literature | 8-bit supported |
| MedAlpaca | `medalpaca/medalpaca-7b` | 7B | Medical instruction-following | 8-bit supported |
| PMC-LLaMA | `axiong/PMC_LLaMA_13B` | 13B | PubMed Central clinical data | 8-bit supported |

### 12.3 Fine-Tuning Candidates (Beta Symptom Checker)

| Model | HuggingFace ID | Size | Pre-training Base | Recommendation |
|---|---|---|---|---|
| BioMistral-7B | `BioMistral/BioMistral-7B` | 7B | Mistral + PubMed Central | Strong biomedical knowledge |
| Meditron-7B | `epfl-llm/meditron-7b` | 7B | LLaMA + clinical guidelines | Best for symptom checker — clinical triage alignment |
| MedMO-8B-Next | `MBZUAI/MedMO-8B-Next` | 8B | MBZUAI medical corpus | Best if Arabic fine-tuning added later |

Fine-tuning method: LoRA (Low-Rank Adaptation) with 8-bit quantization. Framework: Hugging Face PEFT + TRL SFTTrainer. Serving: vLLM with OpenAI-compatible endpoint.

### 12.4 Chart / Visual LLMs (role: chart)

Used exclusively by the Chart Agent, Infographic Agent, and Diagram Agent across all services. These are code-generation models optimized for producing HTML/JS/CSS and SVG. Open-source models are first-class options — switching from cloud to a local open-source model (e.g. Qwen2.5-Coder-7B) saves significant cost since visual generation is frequent across all five module services.

| Model | Type | HuggingFace ID / Provider | Notes |
|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | Local (vLLM) | `Qwen/Qwen2.5-Coder-7B-Instruct` | Excellent HTML/JS/CSS generation, 7B efficient, strong instruction-following |
| DeepSeek-Coder-V2-Lite-Instruct | Local (vLLM) | `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | 16B MoE (memory-efficient), strong structured output |
| CodeLlama-7b-Instruct | Local (vLLM) | `meta-llama/CodeLlama-7b-Instruct-hf` | Widely supported, reliable HTML generation |
| WizardCoder-Python-7B | Local (vLLM) | `WizardLM/WizardCoder-Python-7B-V1.0` | Code-focused, strong web output |
| GPT-4o | Cloud | `gpt-4o` | Highest quality, use when maximum visual precision needed |
| Claude 3.5 Sonnet | Cloud | `anthropic/claude-3-5-sonnet-20241022` | Strong code generation, long context |
| Gemini 1.5 Flash | Cloud | `gemini/gemini-1.5-flash` | Fast, cost-effective cloud option |

Admin selects active chart LLM via model-router-service with role `chart`. This is independent of the medical LLM selection — each service has separate active model configs for each role.

### 12.5 Vision Models

| Model | Type | Provider / Library | Use In |
|---|---|---|---|
| LLaVA | Local | Ollama (`llava`) | chatbot, lab, research |
| Gemma 4 | Local | Ollama (`gemma3:4b`) | chatbot, lab, research |
| GPT-4o Vision | Cloud | `openai/gpt-4o` | All vision-capable services |
| Gemini Vision | Cloud | `gemini/gemini-1.5-flash` | All vision-capable services |
| Claude Vision | Cloud | `anthropic/claude-3-5-sonnet-20241022` | All vision-capable services |

### 12.6 STT Models

| Model | Type | Library / API |
|---|---|---|
| Faster Whisper | Local | faster-whisper library |
| ElevenLabs STT | Cloud | ElevenLabs API |
| Google Gemini STT | Cloud | Google API |
| Supertone supertonic-3 | Cloud | `Supertone/supertonic-3` API |

### 12.7 TTS Models

| Model | Type | Library / API |
|---|---|---|
| Edge-TTS | Local | edge-tts library (Microsoft neural voices) |
| ElevenLabs TTS | Cloud | ElevenLabs API |
| Google Gemini TTS | Cloud | Google API |

### 12.8 Embedding Models

Both models run locally, loaded at service startup. Cannot be changed without re-embedding entire knowledge bases.

| Model | Dimension | Domain | Collections |
|---|---|---|---|
| all-MiniLM-L6-v2 | 384 | General semantic | All RAG collections — primary |
| PubMedBERT | 768 | Biomedical domain | All RAG collections — secondary |
| BioSentVec | 700 | Biomedical sentences | Alternative to PubMedBERT |

### 12.9 Local NLP Models (Model Mode for Specialized Tools)

| Model | HuggingFace ID | Used For |
|---|---|---|
| DistilBART CNN | `sshleifer/distilbart-cnn-12-6` | Summarization (model mode) |
| T5-small | `google/t5-small` | Q&A generation (model mode) |
| opus-mt-en-ar | `Helsinki-NLP/opus-mt-en-ar` | English → Arabic translation (model mode) |
| opus-mt-ar-en | `Helsinki-NLP/opus-mt-ar-en` | Arabic → English translation (model mode) |
| nllb-200-600M | `facebook/nllb-200-distilled-600M` | Multilingual translation alternative |

### 12.10 OCR Engines

| Engine | Type | Best For |
|---|---|---|
| PaddleOCR | Local | General documents, offline |
| Mistral OCR | Cloud API | Complex + dense layouts |
| LightOnOCR | Cloud API | Scientific + medical documents |
| Vision LLM (as OCR) | Cloud or local | Handwritten, complex, mixed content |

---

## 13. KV Cache Architecture

KV (Key-Value) cache eliminates redundant computation for prompts sharing a static prefix. MAISYS applies two independent strategies: local LLM KV cache and cloud prompt prefix caching. Both target the static system prompt — identical across all requests in a given service.

### Local LLM KV Cache

Local transformer models recompute attention keys and values for every token on every call. When the system prompt is large and identical across requests, this wastes GPU compute time.

**Mechanism:** HuggingFace supports `past_key_values` — the attention cache computed during a previous forward pass. If the system prompt is identical between requests, the cached KV tensor is reused and only new user query tokens are processed.

**Implementation in shared library:** `shared/llm_client/kv_cache_manager.py` maintains an in-memory dictionary of cached KV states keyed by SHA-256 hash of the system prompt. Maximum 8 entries per process (configurable). On first request, the system prompt is forward-passed and the resulting KV states are stored. On subsequent requests with the same prompt, stored states are reused.

**Benefit:** 20–40% GPU computation time saved per request for PMC-LLaMA-13B. Smaller models (BioGPT, BioMedLM) benefit proportionally.

**Memory note:** KV cache for PMC-LLaMA-13B occupies approximately 2–4 GB additional VRAM. Reduce max entries if VRAM is constrained.

**Scope:** In-memory only, per service instance, not persisted across restarts.

### Cloud Prompt Prefix Caching

Cloud providers cache KV states server-side when the same token prefix appears on repeated calls. The static system prompt is the ideal prefix — identical on every request from every user.

**Anthropic Claude:** Explicit opt-in. The static system prompt is marked with `cache_control: {"type": "ephemeral"}` in the message structure. Cache hit costs 25% of normal input token price. Cache valid approximately 5 minutes.

**OpenAI GPT-4o / GPT-4o-mini:** Automatic for prompts exceeding 1,024 tokens. No markup required. Cache hit costs 50% of normal input token price. Cache valid approximately 5–10 minutes.

**Groq, Cohere, Mistral:** No prefix caching support. Standard pricing on every request.

**What is cached:** Only the static system prompt (same on every request). RAG context and user queries change per request — handled by Redis semantic cache, not KV cache.

### Redis Semantic Cache

Separate from KV cache. Caches complete LLM responses keyed by semantic hash of the query (embedding similarity threshold 0.92 by default). When a user query is semantically near-identical to a recent query, the cached response is returned without calling the LLM.

TTL by content type: medical responses 6 hours, drug responses 12 hours, reference content 24 hours.

---

## 14. Concurrent and Batch Processing Patterns

These patterns are used throughout MAISYS wherever multiple independent operations can run in parallel. They are implemented using utilities in `shared/concurrent/`.

### Concurrent Execution with asyncio.gather

Multiple independent async operations run in parallel using `asyncio.gather`. A semaphore limit is always applied to prevent spawning uncontrolled numbers of coroutines.

Used for:
- Drug-service: all drug pairs analyzed concurrently (e.g. 6 pairs from 4 drugs)
- Lab-service: all per-test LLM explanations generated concurrently (10–40 tests in parallel)
- Research-service: multiple papers uploaded and processed concurrently
- Drug comparison: each drug's profile fetched concurrently before building comparison table
- Symptom-service: Infermedica /conditions details fetched concurrently for top 3 results
- RAG: Medical RAG and Drug RAG searched concurrently; MiniLM and PubMedBERT collections searched concurrently

### Batch Processing for Ingestion

Large ingestion jobs (Drugs.com PDFs, Mayo Clinic scrape data, research paper discovery) are processed in concurrent batches of configurable size (default: 10 items per batch).

Pattern: read chunk → process chunk concurrently → write results → publish progress → repeat.

Used for:
- Drugs.com PDF ingestion (17,432+ PDFs processed in batches)
- Mayo Clinic data ingestion
- Research paper discovery downloads (papers downloaded and ingested in batches of 10)
- Beta training data normalization (large datasets processed in chunks)

### Scheduled Operations

| Operation | Schedule | Reason |
|---|---|---|
| Knowledge base embedding refresh | Weekly | After model updates requiring re-embedding |
| Export file cleanup | Daily | Remove expired export files from storage |
| Beta training run trigger check | Daily | Check if 200+ new GP-approved records accumulated |
| Model metrics aggregation | Hourly | Consolidate usage metrics in model-router-service |

### Progress Reporting Pattern

All long-running operations publish progress events to Redis pub/sub using `shared/progress/publisher.py`. WebSocket handlers in each service subscribe and forward events to the browser in real time. Events follow a standard structure: step name, user-facing message, progress percentage (0–100).

All services use the same standard event types: initializing, extracting, processing, analyzing, generating, finalizing, complete, error.

---

## 15. Real-Time Experience — Streaming, Progress, and Zero Waiting

MAISYS is built so the user never stares at a blank screen or a spinner without knowing what is happening. Every operation that takes more than one second communicates with the user in real time: what is happening now, what comes next, and approximately how long it will take. This is not cosmetic — it is a core architectural requirement applied to every service.

### 15.1 Streaming LLM Responses (Token-by-Token)

For all conversational endpoints (chatbot, drug session results, symptom explanations, lab explanations, research paper chat), the LLM response is streamed token by token to the browser through the WebSocket connection. The user sees text appearing in real time — exactly like Claude or ChatGPT — rather than waiting for the full response to be generated before seeing anything.

**How it works:** LiteLLM supports streaming mode (`stream=True`). Each token chunk is received from the LLM provider as it is generated, forwarded immediately through the WebSocket to the frontend, and appended to the displayed message. The browser renders each new token as it arrives — no buffering, no waiting.

For local LLMs (BioGPT, PMC-LLaMA via vLLM), vLLM's streaming API works the same way — tokens are emitted as generated and forwarded to the browser.

**Citation and visual injection:** When streaming completes, the backend appends citations and triggers the visual orchestrator. The citations appear below the streamed text. Any generated visual appears below the citations. This sequence is predictable — the user sees: text streaming → citations appear → visual generates → complete.

### 15.2 Progress Events System

For multi-step operations (drug interaction analysis with multiple pairs, symptom session processing, lab report extraction, paper ingestion), the backend publishes structured progress events to Redis pub/sub. The WebSocket handler subscribes and forwards each event to the browser in real time.

**Standard progress event structure:**
```
{
  "step":        "step_identifier",
  "message":     "User-facing message describing what is happening now",
  "detail":      "Optional additional detail (e.g. '3 of 6 pairs analyzed')",
  "progress":    45,          ← 0–100 percentage
  "eta_seconds": 12           ← estimated seconds remaining (where calculable)
}
```

**Progress is always honest:** If a step is not easily time-estimable (e.g. LLM generation), the progress bar moves slowly but continuously rather than stopping. The user always sees movement. The ETA is shown when the system can reliably estimate it (e.g. during batch processing with known item counts), hidden when it cannot.

### 15.3 Per-Service Progress Stages

Every operation in every service has defined progress stages. The user sees each stage label as it begins.

**chatbot-service (message response):**
```
 5%  "Understanding your question..."
20%  "Searching medical knowledge base..."
40%  "Enhancing with medical context..."
65%  "Generating your response..."
85%  Streaming begins — text appears token by token
100% "Complete — generating visual summary..." (if visual triggered)
```

**drug-service (interaction check with 4 drugs = 6 pairs):**
```
 5%  "Identifying your medications..."
15%  "Searching drug knowledge base..."
25%  "Analyzing pair 1 of 6: Drug A + Drug B..."
35%  "Analyzing pair 2 of 6: Drug A + Drug C..."
45%  "Analyzing pair 3 of 6..." (continues per pair with detail)
75%  "Calculating overall risk level..."
85%  "Generating safety recommendations..."
95%  "Preparing your results..."
100% Complete
```
The detail field shows exactly which pair is being analyzed and how many remain. The user knows the system is working, not frozen.

**drug-service (Tier 2 web fallback triggered):**
```
(After RAG check fails sufficiency)
50%  "Checking Drugs.com for detailed interaction data..."
65%  "Extracting interaction information..."
75%  "Analyzing results..."
```
The user sees that the system went online for more information — no black box.

**symptom-service (Alpha session, each turn):**
```
 5%  "Processing your answer..."
30%  "Updating symptom analysis..."
60%  "Preparing next question..."
100% Complete (next question appears)
```
On finalization:
```
 5%  "Completing your assessment..."
30%  "Determining urgency level..."
55%  "Retrieving condition information..."
75%  "Preparing your results..."
90%  Streaming explanation begins
100% Complete
```

**lab-service (report processing):**
```
 5%  "Receiving your report..."
15%  "Extracting text from document..."  (or "Analyzing image with vision AI...")
30%  "Identifying tests and values..."
45%  "Found 24 tests — generating explanations..." (detail: actual test count)
50%  "Explaining test 1 of 24: Complete Blood Count..." (updates per test)
85%  "Generating your overall summary..."
90%  "Preparing visual summary..."
100% Complete
```
The user sees the exact test count found and which test is being explained — the progress bar moves visibly with each test.

**research-service (paper discovery job):**
```
 5%  "Extracting search keywords from your description..."
15%  "Searching academic databases..."
25%  "Found 12 relevant papers — retrieving details..."
35%  "Downloading paper 1 of 5: 'Title of Paper'..." (only downloadable ones)
50%  "Processing paper 1: extracting text..."
60%  "Processing paper 2..."
75%  "Indexing papers into your workspace..."
90%  "Preparing discovery report..."
100% "Found 12 papers — 4 added to your workspace, 8 require manual download"
```

**research-service (paper tools — summarize, translate, Q&A):**
```
15%  "Reading paper content..."
40%  "Generating summary..."  (or translating / generating questions)
80%  Streaming begins — result appears token by token
100% Complete
```

### 15.4 Time Estimation

The system provides `eta_seconds` where it can be reliably calculated:

- **Drug pair analysis:** based on average time per pair × remaining pairs
- **Lab test explanation:** based on average time per test × remaining tests
- **Paper discovery download:** based on file size and current download speed
- **Batch ingestion:** based on average processing time per item × remaining items

Where time cannot be estimated reliably (LLM generation time varies by response length), `eta_seconds` is omitted from the event and the frontend shows only the progress bar and message.

### 15.5 Frontend Progress UI Requirements

The frontend receives WebSocket events and renders:

**Progress bar:** always visible during any multi-step operation. Fills smoothly — no jarring jumps. Minimum visible fill speed (even if progress is slow, bar moves slightly to show life).

**Status message:** rendered below or above the progress bar in a consistent location. Updates on each event. Uses the `message` field.

**Detail text:** rendered in smaller text below the status message. Uses the `detail` field. Examples: "3 of 6 pairs analyzed", "Analyzing Complete Blood Count".

**ETA display:** when `eta_seconds` is present, shown as "About 12 seconds remaining". Updates with each event. Disappears when step type changes.

**Streaming text area:** for LLM responses, the text area appears immediately when streaming begins (before any text) so the user knows output is coming. First token appears within milliseconds of streaming start.

**No spinners without information:** MAISYS does not show a plain spinner. Every waiting state shows at minimum: what is happening, what comes next. A spinner may accompany the status message but never appears alone.

### 15.6 Error States in Real Time

If any step fails during a multi-step operation, the progress system publishes an error event immediately:
```
{
  "step":    "error",
  "message": "User-friendly error description",
  "progress": current_progress,
  "partial_results": {...}  ← whatever was completed before the error
}
```
The user sees exactly what succeeded and what failed. Partial results (e.g. 4 of 6 drug pairs analyzed before a timeout) are displayed with a clear indication that some results are incomplete. The user can retry the failed portion or continue with partial data.

---

## 16. Git Branching and CI/CD Pipeline

### Branch Strategy — Three Environments Across Three Clouds

MAISYS uses three long-lived branches, each mapped to one cloud environment with a specific combination of code maturity and data environment.

| Branch | Environment | Cloud | Code | Data | Budget |
|---|---|---|---|---|---|
| `dev` | Development | GCP (GKE) | Dev code (feature branches) | Dev data (test DBs, partial knowledge base) | $300 GCP credits |
| `stage` | Staging | Azure (AKS) | Dev code (same as `dev`) | Production data (full knowledge base, production DB snapshots) | $200 Azure credits |
| `main` | Production | AWS (EKS) | Production code (release-tagged) | Production data (live, authoritative) | $100 AWS credits |

**Dev branch (`dev`):** Where all development happens. Feature branches merge here. GCP runs the full stack with development databases and a partial knowledge base (sufficient for testing, not the complete 17,432-drug corpus). Dev data can be reset, wiped, or re-seeded at any time. Fast iteration — deploy on every push.

**Stage branch (`stage`):** The pre-production gate. Uses the same code as `dev` but runs against production-scale data — the full Medical RAG, the full Drug RAG with DDIMDL, real-scale PostgreSQL. This catches bugs that only appear at production data volumes. Azure is the staging cloud. A database snapshot from AWS production is restored to Azure staging databases periodically (weekly or before each major release). Real users do not access staging — it is internal validation only.

**Main branch (`main`):** Production. Only stable, tested, stage-validated code reaches here. AWS is the production cloud. AWS holds the authoritative production databases and Qdrant collections. The full knowledge base lives here. Real users and all production traffic.

### What "Dev Data" vs "Production Data" Means

**Dev data (GCP — `dev` branch):**
- Dev PostgreSQL databases: test users, synthetic conversations, test sessions
- Dev Qdrant collections (`dev_medical_minilm`, `dev_drug_minilm`, etc.): populated with a representative subset — enough coverage for feature testing, not the complete corpus
- Dev Redis: can be flushed any time
- DDIMDL dataset: ingested in full (CSV files are fixed-size — no cost difference)
- No real user PII — only synthetic test accounts

**Production data (Azure staging + AWS production):**
- Full Medical RAG: all MedlinePlus + Mayo Clinic content
- Full Drug RAG: all 17,432 Drugs.com general PDFs + 6,450+ professional PDFs + DDIMDL 37,264 interactions
- Full PostgreSQL: production user accounts (AWS), stage snapshot of those accounts (Azure)
- Azure staging databases are populated from the latest AWS production backup before major release cycles

### Why Merging Never Causes Cloud Config Conflicts

Application code (service logic, API routes, database schemas, shared library) is identical across all three branches — only the Kustomize overlay differs per cloud. Overlay directories are never touched by feature branches:

```
k8s/
├── base/                  ← Cloud-agnostic manifests — identical for all three clouds
└── overlays/
    ├── gcp/               ← Dev: GCS bucket, Artifact Registry URL, T4 GPU node selector
    ├── azure/             ← Stage: Azure Blob, ACR URL, V100 GPU node selector, Key Vault CSI
    └── aws/               ← Production: S3 bucket, ECR URL, GPU node selector, Secrets Manager
```

Feature branches never touch overlay directories. Merging `dev` → `stage` → `main` produces zero conflicts on cloud config. Each overlay applies only cloud-specific values (registry URLs, storage bucket names, GPU node labels, secret manager references) — the base manifests remain unchanged.

### GitHub Actions Workflow

**On push to any `feature/*` branch:**
Tests only — no build, no deploy. Unit tests + integration tests + lint. Target: under 5 minutes. Failure blocks PR merge.

**On push to `dev`:**
1. Full test suite for changed services
2. Build Docker images for changed services only (path filtering)
3. Push to Google Artifact Registry: `us-central1-docker.pkg.dev/maisys/{service}:dev-{sha}`
4. `kubectl apply -k k8s/overlays/gcp/`
5. Smoke tests against GCP dev endpoints
6. Auto-rollback on failure

**On merge to `stage`:**
1. Full test suite
2. Build images — push to Azure Container Registry: `maisys.azurecr.io/{service}:stage-{sha}`
3. `kubectl apply -k k8s/overlays/azure/`
4. Run extended integration test suite against stage (tests against production-scale data)
5. Notify team: "Stage deployed — ready for validation"
6. Auto-rollback on failure

**On merge to `main` (production release):**
1. Full test suite (must pass 100%)
2. Build release images — push to AWS ECR: `{account}.dkr.ecr.{region}.amazonaws.com/maisys/{service}:release-{sha}`
3. `kubectl apply -k k8s/overlays/aws/`
4. Wait for rollout to complete across all services
5. Smoke tests against AWS production endpoints
6. Auto-rollback if smoke tests fail
7. Notify team on success or failure

**Per-service builds:** Path filters ensure only changed services are rebuilt. Unchanged services keep their current image — no unnecessary rebuilds.

**Rollback:** Each deployment stores the previous image SHA. On smoke test failure, GitHub Actions automatically re-applies the previous SHA. Manual rollback command: `kubectl rollout undo deployment/{service_name}`

---

## 16. Monorepo Project Structure

```
maisys/
│
├── services/
│   │
│   ├── chatbot-service/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── visual/         (chart_agent.py, infographic_agent.py, diagram_agent.py, orchestrator.py, playwright_renderer.py)
│   │   │   ├── voice/          (stt_service.py, tts_service.py, provider_selector.py)
│   │   │   └── ingestion/      (pdf_ingester.py, mayo_ingester.py, medline_ingester.py, file_ingester.py)
│   │   ├── repository/
│   │   ├── models/
│   │   ├── utils/
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── drug-service/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── visual/
│   │   │   └── voice/
│   │   ├── agents/             (orchestrator, drug_lookup, interaction, dosage, comparison, pharmacokinetics, alternative, web_search, drug_acquisition)
│   │   ├── scripts/            (drugs_com_scraper.py — interaction fallback)
│   │   ├── repository/
│   │   ├── models/
│   │   ├── utils/              (rxnorm_client.py, drug_pair_generator.py)
│   │   ├── exceptions/
│   │   ├── ingestion/          (ingest_drugs_pdfs.py, ingest_mayo_drugs.py, ingest_medlineplus_drugs.py, retry_failed_drugs.py, run_drug_ingestion.py)
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── symptom-service/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── visual/
│   │   │   └── voice/
│   │   ├── infermedica/        (client.py, parse.py, diagnosis.py, triage.py, conditions.py, symptoms.py)
│   │   ├── repository/
│   │   ├── models/
│   │   ├── utils/              (stop_condition.py)
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── lab-service/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── visual/
│   │   │   └── voice/
│   │   ├── ocr/                (engine_selector.py, paddle_wrapper.py, mistral_wrapper.py, lighton_wrapper.py, llm_ocr_wrapper.py)
│   │   ├── nlp/                (scispacy_parser.py)
│   │   ├── repository/
│   │   ├── models/
│   │   ├── utils/              (pdf_detector.py)
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── research-service/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── visual/
│   │   │   └── voice/
│   │   ├── agents/             (paper_discovery_agent.py)
│   │   ├── nlp_models/         (distilbart_summarizer.py, t5_qa_generator.py, opus_mt_translator.py, mode_selector.py)
│   │   ├── ocr/                (same 4 engines as lab-service)
│   │   ├── ingestion/          (paper_ingester.py)
│   │   ├── repository/
│   │   ├── models/
│   │   ├── utils/              (semantic_scholar_client.py, citation_formatter.py)
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── auth-service/
│   │   ├── routes/
│   │   ├── services/
│   │   ├── repository/
│   │   ├── models/
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── translation-service/
│   │   ├── routes/
│   │   ├── services/
│   │   ├── repository/
│   │   ├── models/
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── export-service/
│   │   ├── routes/
│   │   ├── services/
│   │   │   └── generators/     (txt_generator.py, docx_generator.py, pdf_generator.py)
│   │   ├── repository/
│   │   ├── models/
│   │   ├── fonts/              (NotoSansArabic.ttf)
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── safety-service/
│   │   ├── routes/
│   │   ├── services/
│   │   ├── models/
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── notification-service/
│   │   ├── routes/
│   │   ├── services/
│   │   ├── repository/
│   │   ├── models/
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── model-router-service/
│   │   ├── routes/
│   │   ├── services/
│   │   ├── repository/
│   │   ├── models/
│   │   ├── exceptions/
│   │   ├── tests/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── admin-service/
│       ├── routes/
│       ├── services/
│       ├── repository/
│       ├── models/
│       ├── exceptions/
│       ├── tests/
│       ├── main.py
│       ├── Dockerfile
│       └── requirements.txt
│
├── shared/                         ← shared library (imported by all services)
│   ├── auth/                       (jwt_handler.py, dependencies.py)
│   ├── chunking/                   (medical_chunker.py, section_detector.py, token_counter.py)
│   ├── concurrent/                 (gather_with_limit.py, batch_processor.py, progress_tracker.py)
│   ├── embedding/                  (minilm_embedder.py, pubmedbert_embedder.py, dual_embedder.py, similarity.py)
│   ├── error_handler/              (handlers.py, exceptions.py, responses.py)
│   ├── llm_client/                 (client.py, providers.py, kv_cache_manager.py, prefix_cache.py)
│   ├── logger/                     (logger.py, middleware.py)
│   ├── models/                     (base.py, pagination.py, common.py)
│   ├── progress/                   (publisher.py, events.py)
│   ├── rate_limiter/               (api_limiter.py, llm_limiter.py, config.py)
│   ├── security/                   (file_validator.py, filename_sanitizer.py, input_sanitizer.py)
│   └── storage/                    (storage_client.py, gcs_backend.py, azure_backend.py)
│
├── frontend/
│   ├── src/
│   │   ├── pages/                  ← 28 pages
│   │   ├── components/             ← shared UI components
│   │   ├── store/                  ← Redux Toolkit slices per module
│   │   ├── api/                    ← Axios client per service
│   │   ├── i18n/                   ← Arabic + English translation files
│   │   ├── hooks/                  ← useWebSocket, useVoice, useRTL, etc.
│   │   └── styles/                 ← Tailwind config, global styles
│   ├── public/
│   ├── Dockerfile
│   └── package.json
│
├── data-pipeline/
│   ├── scrapers/
│   │   ├── drugs_com/
│   │   │   ├── drugs_general_scraper.py
│   │   │   ├── scraper_professional.py
│   │   │   └── retry_failed_drugs.py
│   │   ├── medlineplus/
│   │   │   ├── part1_health_topics/    scraper.py
│   │   │   ├── part2_drugs/            scraper.py
│   │   │   ├── part3_lab_tests/        scraper.py
│   │   │   ├── part4_encyclopedia/     scraper.py
│   │   │   ├── part5_genetics/         scraper.py
│   │   │   └── utils.py
│   │   ├── mayo_clinic/
│   │   │   ├── part1_diseases_conditions/  scraper.py
│   │   │   ├── part2_symptoms/             scraper.py
│   │   │   ├── part3_tests_procedures/     scraper.py
│   │   │   └── part4_drugs/               scraper.py
│   │   ├── infermedica_scraper.py
│   │   └── endlessmedical_scraper.py
│   │
│   ├── beta_training/
│   │   ├── download_medical_datasets.py
│   │   ├── infermedica_to_beta_training.py
│   │   ├── normalizers/
│   │   │   ├── mimic_normalizer.py
│   │   │   ├── primekg_normalizer.py
│   │   │   ├── mit_kg_normalizer.py
│   │   │   ├── mendeley_normalizer.py
│   │   │   └── kaggle_normalizer.py
│   │   ├── merge_and_split.py
│   │   └── quality_checker.py
│   │
│   └── fine_tuning/
│       ├── finetune_lora.py
│       ├── evaluate_model.py
│       └── push_to_vllm.py
│
├── k8s/
│   ├── base/                       ← cloud-agnostic K8s manifests for all 14 services + infra
│   └── overlays/
│       ├── gcp/                    ← Dev: GCP-only patches (GCS, Artifact Registry, T4 GPU)
│       ├── azure/                  ← Stage: Azure-only patches (Blob, ACR, V100 GPU, Key Vault CSI)
│       └── aws/                    ← Production: AWS-only patches (S3, ECR, GPU, Secrets Manager)
│
├── monitoring/
│   ├── prometheus/prometheus.yml
│   ├── grafana/dashboards/
│   └── loki/loki-config.yaml
│
├── .github/
│   └── workflows/
│       ├── test-feature.yml        ← feature/* branches — tests only
│       ├── deploy-gcp.yml          ← dev branch → GCP (development)
│       ├── deploy-azure.yml        ← stage branch → Azure (staging)
│       └── deploy-aws.yml          ← main branch → AWS (production)
│
├── docker-compose.yml              ← local development (all services)
├── alembic.ini                     ← per-service Alembic config (referenced by each service)
└── README.md
```
