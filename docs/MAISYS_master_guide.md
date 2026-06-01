# MAISYS — Master Project Guide

> **The single source of truth for the entire MAISYS platform.**
> Covers product, architecture, modules, agents, deployment, operations, security, and roadmap.
> Written for both developers and non-technical stakeholders.

---

## Table of Contents

### Part 1 — Product
1. [What is MAISYS?](#1-what-is-maisys)
2. [Who It's For](#2-who-its-for)
3. [Module Overview](#3-module-overview)
4. [User Accounts & Access](#4-user-accounts--access)
5. [Frontend — Pages & Structure](#5-frontend--pages--structure)
6. [Domain & Subdomain Structure](#6-domain--subdomain-structure)

### Part 2 — Architecture
7. [System Architecture Overview](#7-system-architecture-overview)
8. [Architecture Pattern — Modular Monolith](#8-architecture-pattern--modular-monolith)
9. [Shared Services Layer](#9-shared-services-layer)
10. [LangGraph — Unified Agent Framework](#10-langgraph--unified-agent-framework)
11. [Shared Tool Nodes](#11-shared-tool-nodes)
12. [LLM Strategy — LiteLLM Unified Interface](#12-llm-strategy--litellm-unified-interface)
13. [Two-Tier Retrieval Pattern](#13-two-tier-retrieval-pattern)
14. [Bilingual Architecture — Arabic & English](#14-bilingual-architecture--arabic--english)
15. [Real-Time Layer — WebSockets & Redis Pub/Sub](#15-real-time-layer--websockets--redis-pubsub)

### Part 3 — Modules
16. [Medical Chatbot](#16-medical-chatbot)
17. [Drug Agent](#17-drug-agent)
18. [Symptom Checker — Alpha](#18-symptom-checker--alpha)
19. [Symptom Checker — Beta](#19-symptom-checker--beta)
20. [Lab Test Explainer](#20-lab-test-explainer)
21. [Research Paper Assistant](#21-research-paper-assistant)

### Part 4 — AI & Models
22. [Model Catalogue](#22-model-catalogue)
23. [Fine-Tuning Strategy — Beta Symptom Checker](#23-fine-tuning-strategy--beta-symptom-checker)
24. [STT — Supertone Integration](#24-stt--supertone-integration)
25. [Model Serving — vLLM](#25-model-serving--vllm)

### Part 5 — Tech Stack
26. [Full Technology Stack](#26-full-technology-stack)
27. [Database Strategy](#27-database-strategy)
28. [Caching Strategy — Redis](#28-caching-strategy--redis)
29. [Storage Strategy](#29-storage-strategy)

### Part 6 — Deployment
30. [Deployment Overview — GCP + Azure](#30-deployment-overview--gcp--azure)
31. [GCP — Testing & Simulation Environment](#31-gcp--testing--simulation-environment)
32. [Azure — Production Environment](#32-azure--production-environment)
33. [Cloud Portability — Switching Between Clouds](#33-cloud-portability--switching-between-clouds)
34. [Kubernetes Architecture](#34-kubernetes-architecture)
35. [CI/CD Pipeline — GitHub Actions](#35-cicd-pipeline--github-actions)
36. [Environment Configuration](#36-environment-configuration)

### Part 7 — Operations
37. [Monitoring & Observability](#37-monitoring--observability)
38. [Logging Strategy](#38-logging-strategy)
39. [Rate Limiting & Timeouts](#39-rate-limiting--timeouts)
40. [Scaling Strategy](#40-scaling-strategy)
41. [Backup & Recovery](#41-backup--recovery)

### Part 8 — Security & Compliance
42. [Security Architecture](#42-security-architecture)
43. [Data Privacy & User Data Handling](#43-data-privacy--user-data-handling)
44. [HIPAA Considerations](#44-hipaa-considerations)
45. [Beta Data & Consent Compliance](#45-beta-data--consent-compliance)

### Part 9 — Roadmap
46. [What's Built](#46-whats-built)
47. [What's Next](#47-whats-next)
48. [Future Vision](#48-future-vision)

### Part 10 — Master Checklist
49. [Platform-Wide Implementation Checklist](#49-platform-wide-implementation-checklist)

---

# PART 1 — PRODUCT

---

## 1. What is MAISYS?

**MAISYS** (Medical AI Systems) is a comprehensive Arabic-and-English medical AI platform that brings together multiple intelligent health tools under a single unified interface. It is designed to make medical knowledge accessible, understandable, and actionable for everyone — from patients checking their symptoms to healthcare professionals researching drug interactions or reviewing clinical literature.

MAISYS is not a diagnostic tool and does not replace medical professionals. It is an intelligent layer that helps users understand medical information, navigate health decisions, and know when to seek professional care.

### What Makes MAISYS Different

- **Bilingual from the ground up**: Arabic and English are first-class citizens throughout — not an afterthought translation layer.
- **Grounded, not hallucinated**: Every module anchors its responses in validated sources — clinical databases, published literature, medical APIs — before using AI to explain them.
- **Modular**: Each health tool is a self-contained module with its own reasoning pipeline, while sharing a common infrastructure.
- **Transparent**: Users always know where information comes from — local knowledge base, web source, or clinical API — and always receive a professional consultation reminder.
- **Safe by design**: Emergency detection, medical disclaimers, and triage urgency are built into every module.

---

## 2. Who It's For

| User Type | How They Use MAISYS |
|---|---|
| **General Public** | Understand symptoms, check medications, decode lab results in plain language |
| **Patients** | Get structured health information and know when to see a doctor |
| **Caregivers** | Check medications and symptoms for family members |
| **Medical Students** | Study drug mechanisms, differential diagnosis, clinical literature |
| **Pharmacists** | Quick drug interaction reference, alternative finder, dosage guidance |
| **Healthcare Professionals** | Off-label use reference, drug comparison, research paper assistant |
| **GP Reviewers (internal)** | Review and label Beta session data to improve the fine-tuned model |
| **Developers & Researchers** | Build on top of MAISYS APIs |

---

## 3. Module Overview

MAISYS consists of six user-facing modules and one internal Beta training system:

### 3.1 Medical Chatbot
A conversational medical assistant that answers general health questions, explains medical concepts, and provides health education in plain Arabic or English. Powered by a LangGraph agent pipeline with RAG-backed medical knowledge and web search fallback.

### 3.2 Drug Agent
A comprehensive drug information hub covering: drug profile lookup, brand/generic conversion, drug class browser, drug–drug interaction checking, drug–food and drug–disease interaction checking, pregnancy and breastfeeding safety, dosage calculator, drug alternative finder, drug comparison, pharmacokinetics viewer, and off-label use explorer. Uses a two-tier retrieval system (local RAG → Drugs.com live scraping fallback). All drug reasoning backed by RxNorm normalization.

### 3.3 Symptom Checker — Alpha (Production)
A clinically-grounded conversational symptom assessment tool. The user describes symptoms, answers follow-up questions, and receives a structured triage recommendation. Powered by a hybrid engine: **Infermedica** handles all medical reasoning (diagnosis probabilities, triage level), while the **LLM** handles all language (rephrasing questions, explaining results in plain language, generating triage summaries).

### 3.4 Symptom Checker — Beta (Training)
An experimental parallel symptom checker powered by a fine-tuned open-source medical LLM — not Infermedica. Completely isolated from Alpha. Available only to triple-consented users. Responses are clearly labelled as experimental and not for clinical use. Anonymized, GP-reviewed session data continuously improves the model.

### 3.5 Lab Test Explainer
Explains laboratory test results in plain language. Users enter a test name and result value and receive: what the test measures, what the result means, normal reference ranges, and what abnormal values may indicate. Always includes a recommendation to discuss results with a physician.

### 3.6 Research Paper Assistant
Helps users find, summarize, and analyze medical and scientific research papers. Supports uploading PDFs, searching PubMed, parallel multi-paper analysis, and structured comparison of findings across papers.

---

## 4. User Accounts & Access

### 4.1 Authentication Flow

```
User registers with email + password
        ↓
OTP verification (email or phone)
        ↓
Optional: connect Google or Apple OAuth
        ↓
Account active — full module access
```

All modules are free — no subscription required.

### 4.2 What Accounts Enable

- Session history across all modules
- Saved/bookmarked results
- Language preference (Arabic / English)
- Beta Symptom Checker access (after triple consent)
- Account security settings (OTP, connected accounts)
- Export history

### 4.3 Anonymous Access

Basic module access is available without an account — but history, saved results, and Beta access require authentication.

### 4.4 Admin Accounts

Separate authentication system at `admin.maisys.x`. Two roles:
- **GP Reviewer**: access to Beta review queue only
- **System Admin**: full admin panel (user management, monitoring, model tracking)

---

## 5. Frontend — Pages & Structure

### 5.1 Technology

- **Framework**: React + TypeScript
- **Styling**: Tailwind CSS
- **State**: Redux Toolkit
- **HTTP**: Axios
- **WebSocket**: Native WebSocket API
- **i18n**: react-i18next (Arabic + English)
- **Theme**: Light + Dark mode toggle
- **Notifications**: react-hot-toast
- **Icons**: lucide-react
- **File downloads**: file-saver

### 5.2 Complete Page List

#### Public Pages (unauthenticated)
| # | Page | Route | Description |
|---|---|---|---|
| 1 | Landing Page | `/` | Hero section, feature highlights, module cards, CTA to register |
| 2 | About | `/about` | What MAISYS is, mission, team |
| 3 | How It Works | `/how-it-works` | Step-by-step explainer per module |
| 4 | Contact / Support | `/contact` | Support form + contact info |
| 5 | Privacy Policy | `/privacy` | Data handling, user rights |
| 6 | Terms of Use | `/terms` | Usage terms and limitations |
| 7 | Login | `/login` | Email/password + OAuth buttons |
| 8 | Register | `/register` | Registration form |
| 9 | Forgot Password | `/forgot-password` | Password reset request |
| 10 | Reset Password | `/reset-password` | New password form (via token) |
| 11 | OTP Verification | `/verify-otp` | Phone/email OTP confirmation |
| 12 | Email Verification | `/verify-email` | Email link confirmation |

#### Authenticated App — Dashboard
| # | Page | Route | Description |
|---|---|---|---|
| 13 | Main Dashboard | `/dashboard` | Module selector, recent activity, quick access cards |
| 14 | Profile & Settings | `/settings/profile` | Name, avatar, language preference |
| 15 | Security Settings | `/settings/security` | Password change, OTP, connected OAuth accounts |
| 16 | History | `/history` | All past sessions across all modules |
| 17 | Saved Results | `/saved` | Bookmarked/starred sessions |
| 18 | Beta Consent & Settings | `/settings/beta` | All 3 consent gates + withdrawal option |

#### Module Pages
| # | Page | Route | Description |
|---|---|---|---|
| 19 | Medical Chatbot | `/chatbot` | Conversational health assistant UI |
| 20 | Drug Agent | `/drugs` | Tabbed interface for all 12 drug features |
| 21 | Symptom Checker Alpha | `/symptoms` | Full Alpha conversation flow |
| 22 | Symptom Checker Beta | `/symptoms/beta` | Beta flow — gated behind triple consent |
| 23 | Lab Test Explainer | `/labs` | Lab test lookup and result explanation |
| 24 | Research Paper Assistant | `/research` | Paper search, upload, summary, comparison |

#### Admin Panel (`admin.maisys.x`)
| # | Page | Route | Description |
|---|---|---|---|
| 25 | Admin Login | `/login` | Separate auth for admin/GP |
| 26 | GP Review Dashboard | `/review` | Beta session review queue — approve/correct/reject |
| 27 | System Monitoring | `/monitoring` | Usage stats, error rates, API health, model latency |
| 28 | User Management | `/users` | View users, manage accounts, revoke access |
| 29 | Model Performance Tracker | `/models` | Training runs, accuracy over time, deployed version |

### 5.3 Layout Structure

```
app.maisys.x
├── Public layout (no sidebar)
│   ├── Navbar: Logo + nav links + Login/Register CTA + Language toggle + Theme toggle
│   └── Footer: Links + disclaimer + copyright
│
└── Authenticated layout
    ├── Sidebar: Module navigation + user avatar + settings
    ├── Top bar: Search + notifications + language + theme
    └── Main content area: module pages rendered here
```

### 5.4 RTL/LTR Layout

When language is Arabic, the entire layout switches to RTL:
- Sidebar moves to the right
- Text alignment flips
- Export files use Arabic font (Noto Sans Arabic) with RTL layout
- All module UIs adapt — input fields, buttons, tables, progress bars

---

## 6. Domain & Subdomain Structure

### 6.1 Domain

| Option | Status |
|---|---|
| `maisys.org` | Preferred candidate |
| `maisys.cloud` | Preferred candidate |

Final selection to be confirmed. Registrar: **Cloudflare** (70% confirmed) for domain registration, DNS management, CDN, and DDoS protection in one place.

### 6.2 Subdomain Map

| Subdomain | Purpose | Points To |
|---|---|---|
| `app.maisys.x` | Main frontend application | GCP/Azure frontend service |
| `api.maisys.x` | Backend API gateway | GCP/Azure backend service |
| `admin.maisys.x` | Admin + GP review panel | Separate admin frontend |
| `chatbot.maisys.x` | Medical Chatbot module | Module route alias |
| `drugs.maisys.x` | Drug Agent module | Module route alias |
| `symptoms.maisys.x` | Symptom Checker module | Module route alias |
| `labs.maisys.x` | Lab Test Explainer module | Module route alias |
| `research.maisys.x` | Research Paper Assistant | Module route alias |
| `beta.maisys.x` | Beta Symptom Checker | Module route alias |

### 6.3 SSL/TLS

Cloudflare provides automatic SSL for all subdomains via wildcard certificate (`*.maisys.x`). All HTTP traffic redirected to HTTPS automatically.

---

# PART 2 — ARCHITECTURE

---

## 7. System Architecture Overview

```
                        ┌─────────────────────────────┐
                        │   Cloudflare CDN + DNS       │
                        │   DDoS Protection + SSL      │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │   app.maisys.x (Frontend)   │
                        │   React + TypeScript        │
                        │   Tailwind + Redux          │
                        └──────────────┬──────────────┘
                                       │ HTTPS / WebSocket
                        ┌──────────────▼──────────────┐
                        │   api.maisys.x (API Gateway)│
                        │   FastAPI + Uvicorn         │
                        │   Rate Limiting + Auth      │
                        └──────┬───────────────┬──────┘
                               │               │
              ┌────────────────▼──┐    ┌───────▼───────────────┐
              │  Module Services  │    │  Shared Services      │
              │  (one per module) │    │  Auth, Translation,   │
              │                   │    │  Export, Safety       │
              └────────┬──────────┘    └───────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │   LangGraph Agent Layer    │
         │   Module-specific graphs   │
         │   + Shared tool nodes      │
         └──┬──────────────────────┬──┘
            │                      │
  ┌─────────▼──────┐    ┌──────────▼─────────┐
  │  LLM Layer     │    │  Retrieval Layer    │
  │  LiteLLM       │    │  Tier 1: Qdrant RAG │
  │  (cloud/local) │    │  Tier 2: Web search │
  │  vLLM (local)  │    │  + Scraping        │
  └────────────────┘    └────────────────────┘
            │
  ┌─────────▼──────────────────────────┐
  │  Data Layer                        │
  │  PostgreSQL  Redis  Qdrant         │
  │  GCS/Azure Blob (object storage)   │
  └────────────────────────────────────┘
```

---

## 8. Architecture Pattern — Modular Monolith

All MAISYS modules are deployed as a **Modular Monolith** — a single deployable FastAPI application with clean internal module boundaries. Each module has its own routes, services, agents, and repository layer, but they share infrastructure: one database, one Redis instance, one Qdrant instance, one LLM client, and one shared tool layer.

### Why Not Microservices

**1. Shared LLM and embedding models.** Medical LLMs loaded at startup are shared across modules. In microservices, each service would need its own model instance — extremely wasteful for 7B+ parameter models.

**2. LangGraph agents are intra-process.** Agent graphs share state and tool nodes in memory. Distributing them across services would require message brokers and remote state, adding complexity with no benefit at current scale.

**3. Session state is tightly coupled.** The Symptom Checker session, the Drug Agent comparison pipeline, and the Research Paper parallel analysis all depend on in-process state management via Redis. Cross-service calls would add latency to every conversational turn.

**4. Consistent deployment.** One container, one Dockerfile, one Kubernetes deployment per module service. Easier to test, monitor, and scale.

### When to Extract a Service

Extract a module to its own service when:
- It has dramatically different scaling needs (e.g. vLLM model server already runs separately)
- It needs a different runtime (e.g. Python ML vs Go API gateway)
- The team owning it is independent

---

## 9. Shared Services Layer

These services are available to all modules — no module implements them independently:

| Shared Service | Responsibility | Used By |
|---|---|---|
| **AuthService** | JWT token validation, user session, OAuth | All modules |
| **TranslationService** | Arabic ↔ English via deep-translator | Chatbot, Drug Agent, Symptom Checker |
| **ExportService** | TXT / DOCX / PDF generation, Arabic RTL | All modules |
| **SafetyService** | Emergency detection, disclaimer injection | Symptom Checker, Chatbot, Drug Agent |
| **CacheService** | Redis cache-aside pattern, TTL management | All modules |
| **StorageService** | GCS / Azure Blob abstraction | Research Paper, Export |
| **NotificationService** | Email OTP, verification emails | Auth flow |

---

## 10. LangGraph — Unified Agent Framework

### 10.1 Why LangGraph for MAISYS

LangGraph is the unified agent framework across all MAISYS modules. It was chosen over CrewAI and plain LangChain for four reasons:

**Stateful by design.** The Symptom Checker conversation, the Drug Agent multi-step comparison, and the Research Paper parallel analysis all require state that persists across multiple agent steps. LangGraph's `StateGraph` carries typed state through every node — no manual state threading.

**Native human-in-the-loop.** MAISYS uses a hybrid execution model: autonomous by default, with `interrupt()` injected at high-stakes points (triage emergency, drug contraindication, low-confidence Beta response). LangGraph's `interrupt()` and `Command(resume=...)` pattern handles this natively.

**Shared tool nodes.** Tool nodes (web search, RAG retrieval, translation, RxNorm) are defined once and reused across all module graphs. No duplication.

**Streaming to WebSocket.** LangGraph's `.astream_events()` emits granular step-level events that map directly to WebSocket progress updates — users see real-time progress as the agent works.

### 10.2 Graph Structure per Module

Each module defines its own `StateGraph`. All graphs share the same tool node registry.

```python
# Simplified structure — Drug Agent interaction graph
from langgraph.graph import StateGraph, END
from app.shared.tools import web_search_tool, rag_tool, rxnorm_tool

class DrugInteractionState(TypedDict):
    drug_names: list[str]
    normalized: list[dict]
    pairs: list[tuple]
    pair_results: list[dict]
    overall_risk: str
    language: str

graph = StateGraph(DrugInteractionState)

graph.add_node("normalize",    normalize_drugs_node)
graph.add_node("generate_pairs", generate_pairs_node)
graph.add_node("retrieve",     rag_retrieval_node)       # shared tool node
graph.add_node("evaluate",     sufficiency_eval_node)
graph.add_node("web_fallback", web_search_node)          # shared tool node
graph.add_node("analyze",      llm_analysis_node)
graph.add_node("aggregate",    risk_aggregation_node)

graph.set_entry_point("normalize")
graph.add_edge("normalize", "generate_pairs")
graph.add_edge("generate_pairs", "retrieve")
graph.add_conditional_edges("evaluate", route_tier,
    {"sufficient": "analyze", "insufficient": "web_fallback"})
graph.add_edge("web_fallback", "analyze")
graph.add_edge("analyze", "aggregate")
graph.add_edge("aggregate", END)
```

### 10.3 Human-in-the-Loop Pattern

```python
# High-stakes interrupt example — emergency triage in Symptom Checker
from langgraph.types import interrupt, Command

def triage_node(state: SymptomState):
    triage = infermedica.get_triage(state)

    if triage["level"] in ["emergency", "emergency_ambulance"]:
        # Pause graph — surface emergency to user
        user_response = interrupt({
            "type": "emergency_alert",
            "message": "⚠️ Your symptoms may indicate a medical emergency.",
            "action": "Call emergency services immediately.",
            "confirm": "Do you need help finding emergency services near you?"
        })
        return Command(resume={"emergency_confirmed": True})

    return {"triage_level": triage["level"]}
```

### 10.4 Streaming to WebSocket

```python
# Stream LangGraph events to Redis Pub/Sub → WebSocket
async def run_with_streaming(graph, state, session_id):
    async for event in graph.astream_events(state, version="v2"):
        if event["event"] == "on_chain_start":
            await redis.publish(f"progress:{session_id}", json.dumps({
                "step": event["name"],
                "message": STEP_MESSAGES.get(event["name"], "Processing..."),
                "progress": STEP_PROGRESS.get(event["name"], 50)
            }))
```

---

## 11. Shared Tool Nodes

These LangGraph tool nodes are defined once in `app/shared/tools/` and imported by any module graph:

| Tool Node | File | Used By |
|---|---|---|
| `web_search_tool` | `web_search.py` | Drug Agent, Chatbot, Research Paper |
| `rag_retrieval_tool` | `rag_retrieval.py` | Drug Agent, Chatbot, Lab Test, Research Paper |
| `drugs_com_scraper_tool` | `drugs_com_scraper.py` | Drug Agent (interaction fallback) |
| `rxnorm_tool` | `rxnorm.py` | Drug Agent |
| `translation_tool` | `translation.py` | Chatbot, Symptom Checker, Drug Agent |
| `pdf_reader_tool` | `pdf_reader.py` | Research Paper, Lab Test |
| `infermedica_tool` | `infermedica.py` | Symptom Checker Alpha |

### Shared Tool Node Pattern

```python
# app/shared/tools/rag_retrieval.py
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool

@tool
async def rag_retrieval(query: str, collection: str,
                        section_filter: str = None, top_k: int = 8) -> list[dict]:
    """Search the MAISYS RAG knowledge base. Returns relevant document chunks."""
    return await retriever.search(query, collection, section_filter, top_k)

rag_tool_node = ToolNode([rag_retrieval])
```

---

## 12. LLM Strategy — LiteLLM Unified Interface

All LLM calls across MAISYS go through a single `UnifiedLLMClient` backed by LiteLLM. Changing the LLM provider requires only a `.env` update — no code changes in any module.

```python
# app/shared/llm/unified_client.py
import litellm

class UnifiedLLMClient:
    def __init__(self, model: str):
        self.model = model  # from settings.LLM_MODEL

    async def generate(self, system: str, user: str,
                       temperature: float = 0.1) -> str:
        response = await litellm.acompletion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user}
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content

    async def generate_with_confidence(self, system: str, user: str) -> dict:
        """Returns answer + confidence score for sufficiency evaluation."""
        raw = await self.generate(system + CONFIDENCE_SUFFIX, user)
        return json.loads(raw)  # {"answer": "...", "confidence": 0.0-1.0}
```

**Supported providers (`.env` switch only):**

| Provider | Model String |
|---|---|
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Anthropic | `claude-3-5-sonnet-20241022` |
| Google Gemini | `gemini/gemini-1.5-pro` |
| Groq | `groq/llama-3.1-70b-versatile` |
| Mistral | `mistral/mistral-large-latest` |
| Azure OpenAI | `azure/gpt-4o` |
| Self-hosted vLLM | `openai/BioMistral-7B` (vLLM OpenAI-compatible endpoint) |

---

## 13. Two-Tier Retrieval Pattern

The Drug Agent and Medical Chatbot use a two-tier retrieval system. This pattern is available as a shared component for any future module that needs it.

```
TIER 1: Local RAG (Qdrant)
        ↓
SufficiencyEvaluator
  chunk_count >= 3  AND  llm_confidence >= 0.75
        ↓ PASS                    ↓ FAIL
  Return local result        TIER 2: Web fallback
  (source: local KB)    ┌────────────────────────┐
                        │ Drug–drug interaction: │
                        │ Playwright → drugs.com │
                        │                        │
                        │ All other features:    │
                        │ CrewAI SerperDevTool    │
                        └────────────────────────┘
                              ↓
                        LLM generates from web content
                        source_label: "🌐 Web Source"
                        citation: full URL
```

Both thresholds are configurable via `.env`:
```
MIN_RAG_CHUNKS=3
MIN_LLM_CONFIDENCE=0.75
```

---

## 14. Bilingual Architecture — Arabic & English

Arabic is a first-class language throughout MAISYS. The bilingual architecture works as follows:

### For modules that call external English-only APIs (Infermedica, RxNorm):

```
User input (Arabic)
        ↓
TranslationService.to_english()
        ↓
External API (English)
        ↓
LLM processes response
        ↓
TranslationService.to_arabic() (if needed)
        ↓
User sees Arabic response
```

### For modules using only internal LLM:

```
User input (Arabic or English)
        ↓
Language detected / set from session
        ↓
LLM prompt includes: "Language: {language}" instruction
        ↓
LLM generates directly in the correct language
```

### Export RTL support:

All exports (PDF, DOCX) check session language. If Arabic:
- DOCX: `paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT` + Noto Sans Arabic font
- PDF: fpdf2 RTL mode + Noto Sans Arabic font loaded from `/fonts/NotoSansArabic.ttf`

---

## 15. Real-Time Layer — WebSockets & Redis Pub/Sub

Every module that runs multi-step agent pipelines streams progress to the user via WebSocket. The pattern is consistent across all modules:

```
LangGraph agent step completes
        ↓
Service publishes event to Redis channel: progress:{session_id}
        ↓
WebSocket handler subscribed to that channel
        ↓
Event forwarded to browser via WebSocket
        ↓
Frontend progress bar updates in real time
```

```python
# app/api/websocket.py (shared across all modules)
@app.websocket("/ws/{session_id}")
async def progress_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"progress:{session_id}")
    async for message in pubsub.listen():
        if message["type"] == "message":
            await websocket.send_text(message["data"])
        if message["data"] == '{"step":"complete"}':
            break
    await websocket.close()
```

---

# PART 3 — MODULES

---

## 16. Medical Chatbot

**Purpose**: Conversational general medical assistant — answers health questions, explains medical concepts, provides health education.

**Architecture**: Modular Monolith, LangGraph agent

**Agent graph nodes**:
1. `intent_classifier` — classifies query: general health / drug / symptom / emergency
2. `rag_retrieval` (shared tool) — searches medical knowledge base
3. `sufficiency_eval` — checks if RAG result is sufficient
4. `web_search` (shared tool) — fallback if RAG insufficient
5. `response_generator` — LLM generates cited response
6. `safety_check` — emergency detection + disclaimer injection

**STT integration**: Supertone STT for voice input — user can speak instead of type

**Key features**: Multi-turn conversation, session memory, source citations, Arabic/English, voice input, export conversation as PDF/DOCX/TXT

**Guide reference**: `medical_chatbot_guide.md`

---

## 17. Drug Agent

**Purpose**: Comprehensive drug information hub — 12 features covering drug info, safety, interactions, dosage, and clinical tools.

**Architecture**: Modular Monolith, LangGraph agent graphs (migrated from CrewAI)

**Two-tier retrieval**: Local RAG (Drugs.com ingested) → Playwright scrape (drug–drug) / web search (all other features)

**Drug name normalization**: RxNorm API → scispaCy fallback

**Agent graphs**: DrugLookup, Interaction, Dosage, Comparison, Pharmacokinetics, Alternative

**Key features**: 12 drug features, RxNorm normalization, dual-embedding RAG (MiniLM + PubMedBERT), Drugs.com live scraping fallback, source tier labels, Arabic/English, PDF/DOCX/TXT export

**Guide reference**: `drug_agent_guide.md`

---

## 18. Symptom Checker — Alpha

**Purpose**: Production-grade conversational symptom assessment powered by Infermedica.

**Architecture**: Modular Monolith, hybrid Infermedica + LLM engine

**Infermedica endpoints used**: `/parse`, `/diagnosis`, `/triage`, `/conditions`, `/symptoms`

**LLM roles**: Rephrase questions, parse answers, explain results, generate triage summary

**Session flow**: Initial form → `/parse` → `/diagnosis` loop (5–8 turns) → `/triage` → `/conditions` → LLM explanation

**Stop conditions**: `should_stop` from Infermedica, turn limit (8), high probability (≥0.85), clear probability gap (≥0.5)

**Key features**: Bilingual, triage color coding, emergency detection, Arabic RTL export, session history

**Guide reference**: `symptom_checker_guide.md` (Part One)

---

## 19. Symptom Checker — Beta

**Purpose**: Experimental fine-tuned LLM symptom checker — under training, not for clinical use.

**Access**: Triple-consented users only (explicit screen + account settings + onboarding)

**Model**: Fine-tuned open-source medical LLM (BioMistral-7B / Meditron-7B / MedMO-8B-Next — one selected)

**Data pipeline**: Real sessions (consented) + ingested datasets (CSV/JSON/clinical notes/Q&A) → anonymization → GP review → JSONL training dataset → LoRA fine-tuning → evaluation → deployment

**Fine-tuning**: LoRA on base model, 8-bit quantization, Hugging Face + PEFT + TRL

**Serving**: vLLM (production), Ollama/HF (dev)

**Key features**: Triple consent, anonymization, GP review queue, continuous improvement loop, ⚠️ BETA watermark on all outputs

**Guide reference**: `symptom_checker_guide.md` (Part Two)

---

## 20. Lab Test Explainer

**Purpose**: Explains laboratory test results in plain language.

**Architecture**: Modular Monolith, LangGraph agent

**Agent graph nodes**:
1. `test_identifier` — identifies test from name/code
2. `rag_retrieval` (shared tool) — searches lab test knowledge base
3. `result_interpreter` — LLM interprets result vs reference range
4. `response_generator` — plain-language explanation

**Key features**: Test name lookup, result value + unit input, reference range comparison, abnormal value explanation, always recommends physician consultation, Arabic/English, export

**Guide reference**: `lab_test_explainer.md`

---

## 21. Research Paper Assistant

**Purpose**: Find, summarize, and analyze medical and scientific research papers.

**Architecture**: Modular Monolith, LangGraph agent with parallel execution

**Agent graph nodes**:
1. `query_builder` — builds PubMed/search queries from user input
2. `paper_fetcher` — searches PubMed API or accepts PDF upload
3. `parallel_analyzer` — runs analysis on multiple papers concurrently
4. `synthesizer` — LLM synthesizes findings across papers
5. `comparison_builder` — structured comparison table if multiple papers

**Key features**: PubMed search, PDF upload, parallel multi-paper analysis, structured comparison, citation export, Arabic/English

**Guide reference**: `guide_Parallel.md`

---

# PART 4 — AI & MODELS

---

## 22. Model Catalogue

### 22.1 Fine-Tuning Candidates — Beta Symptom Checker

All three models are medically pre-trained open-source LLMs. One will be selected for the first Beta fine-tuning run.

| Model | HF ID | Size | Pre-training | Strength | Consideration |
|---|---|---|---|---|---|
| **BioMistral-7B** | `BioMistral/BioMistral-7B` | 7B | PubMed Central (biomedical literature) | Strong biomedical domain knowledge, well-documented | Best starting point for clinical tasks |
| **Meditron-7B** | `epfl-llm/meditron-7b` | 7B | Clinical guidelines + medical literature (EPFL) | Specifically trained on clinical guidelines — strong triage reasoning | Ideal for symptom checker use case |
| **MedMO-8B-Next** | `MBZUAI/MedMO-8B-Next` | 8B | MBZUAI medical corpus | Strong multilingual medical capability, Arabic-aware base | Best option if Arabic fine-tuning becomes needed |

**Recommendation**: Start with **Meditron-7B** for the Beta Symptom Checker — its clinical guideline training aligns directly with triage and differential diagnosis tasks. If Arabic fine-tuning is added later, migrate to MedMO-8B-Next.

### 22.2 Cloud LLMs via LiteLLM (Production Alpha)

Used for all Alpha module responses. Provider switched via `.env` only.

| Provider | Recommended Model | Use Case |
|---|---|---|
| OpenAI | `gpt-4o` | Best overall quality |
| OpenAI | `gpt-4o-mini` | Extraction tasks, lower cost |
| Anthropic | `claude-3-5-sonnet-20241022` | Long context, nuanced explanations |
| Google | `gemini/gemini-1.5-pro` | Large context, multilingual |
| Groq | `groq/llama-3.1-70b-versatile` | Fast inference, lower cost |

### 22.3 Embedding Models (RAG)

| Model | Used For | Collection |
|---|---|---|
| `all-MiniLM-L6-v2` | General semantic search | All RAG collections (primary) |
| `PubMedBERT` | Biomedical domain search | Drug Agent RAG collections |

### 22.4 STT Model

| Model | HF ID | Used In |
|---|---|---|
| **Supertonic-3** | `Supertone/supertonic-3` | Medical Chatbot voice input, any module requiring STT |

---

## 23. Fine-Tuning Strategy — Beta Symptom Checker

### 23.1 Data Sources

| Source | Format | Pipeline |
|---|---|---|
| Consented Beta sessions | JSON (structured) | Session collector → anonymizer → GP review |
| Clinical notes / transcripts | Unstructured text | LLM extractor → cleaner → validator |
| Symptom–diagnosis datasets | CSV / JSON | Schema mapper → validator |
| Medical Q&A pairs | JSON / text | QA formatter → validator |
| Custom / other formats | Various | Format router → LLM extractor |

All sources → **Unified schema** → **GP review queue** → **JSONL training dataset**

### 23.2 Fine-Tuning Method — LoRA

- Base model: Meditron-7B (or selected alternative)
- Adapter: LoRA (`r=16`, `lora_alpha=32`, target: `q_proj`, `v_proj`)
- Quantization: 8-bit (`load_in_8bit=True`) to reduce VRAM
- Framework: Hugging Face PEFT + TRL SFTTrainer
- Training format: Instruction tuning (JSONL)

### 23.3 Quality Gates

- Minimum 500 GP-approved records before first training run
- 80% train / 10% validation / 10% test split
- Class balance: no diagnosis > 40% of records
- Triage distribution: all levels represented
- Evaluation: triage accuracy ≥ 85%, top-condition accuracy ≥ 70% before deployment

### 23.4 Continuous Improvement Loop

```
New consented Beta sessions
        ↓ (anonymized automatically)
GP review queue
        ↓ (GP approves / corrects / rejects)
Training dataset grows
        ↓ (trigger: 200+ new records OR monthly)
LoRA fine-tuning run
        ↓
Evaluation on test set
        ↓ (if improved)
New model version deployed to Beta vLLM server
```

---

## 24. STT — Supertone Integration

**Model**: `Supertone/supertonic-3`
**Used in**: Medical Chatbot (primary), any module with voice input

### Integration Pattern

```python
# app/shared/stt/supertone_client.py
import httpx

class SupertoneSTTClient:
    async def transcribe(self, audio_bytes: bytes,
                         language: str = "ar") -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.supertone.ai/v1/transcribe",
                headers={"Authorization": f"Bearer {settings.SUPERTONE_API_KEY}"},
                files={"audio": audio_bytes},
                data={"language": language, "model": "supertonic-3"}
            )
            return response.json()["text"]
```

**Dev environment**: Loaded locally via Hugging Face Transformers
**Production**: API call to Supertone hosted endpoint or self-hosted via vLLM-compatible inference

---

## 25. Model Serving — vLLM

vLLM provides OpenAI-compatible API endpoints for self-hosted models, making the switch from cloud LLMs to local models transparent to the application layer.

### vLLM Deployment (Kubernetes)

```yaml
# k8s/vllm-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-server
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        args:
          - "--model"
          - "epfl-llm/meditron-7b"          # or selected fine-tuned model
          - "--quantization"
          - "awq"
          - "--max-model-len"
          - "4096"
          - "--served-model-name"
          - "meditron-7b"
        resources:
          limits:
            nvidia.com/gpu: 1
        ports:
        - containerPort: 8000
```

**LiteLLM connects to vLLM** via OpenAI-compatible endpoint:
```
LLM_MODEL=openai/meditron-7b
OPENAI_API_BASE=http://vllm-server:8000/v1
OPENAI_API_KEY=not-needed
```

No code changes anywhere — LiteLLM routes to vLLM exactly like it routes to OpenAI.

---

# PART 5 — TECH STACK

---

## 26. Full Technology Stack

### Frontend

| Category | Technology | Version |
|---|---|---|
| Framework | React | 18 |
| Language | TypeScript | 5 |
| Styling | Tailwind CSS | 3 |
| State | Redux Toolkit | 2 |
| HTTP | Axios | 1.6 |
| WebSocket | Native WebSocket API | — |
| i18n | react-i18next | 14 |
| Notifications | react-hot-toast | 2 |
| File download | file-saver | 2 |
| Icons | lucide-react | 0.383 |
| Build | Vite | 5 |

### Backend

| Category | Technology | Version |
|---|---|---|
| Framework | FastAPI | 0.109 |
| Server | Uvicorn | 0.27 |
| Agent Framework | LangGraph | 0.2+ |
| LLM Orchestration | LangChain | 0.1 |
| LLM Interface | LiteLLM | latest |
| Model Serving | vLLM | latest |
| Transformers | Hugging Face Transformers | 4.36 |
| Fine-tuning | PEFT + TRL | latest |
| Embedding | sentence-transformers | 2.2 |
| Vector DB client | qdrant-client | 1.7 |
| Web scraping | Playwright (async) | 1.40 |
| HTML parsing | BeautifulSoup4 | 4.12 |
| Web search | SerpAPI / SerperDev | — |
| Medical NLP | scispaCy + en_core_sci_md | 0.5 |
| Drug normalization | httpx → RxNorm REST | — |
| STT | Supertone API / HF Transformers | — |
| Translation | deep-translator | 1.9 |
| DOCX export | python-docx | 1.1 |
| PDF export | fpdf2 / reportlab | latest |
| Validation | Pydantic | 2.5 |
| ORM | SQLAlchemy (async) | 2.0 |
| Migrations | Alembic | 1.13 |
| Logging | structlog + loguru | — |
| Rate limiting | slowapi | 0.1 |
| Auth | python-jose + passlib | — |
| Config | python-dotenv | 1.0 |
| Deep learning | PyTorch | 2.1 |
| Data processing | pandas | 2.1 |
| HTTP client | httpx | 0.26 |

### Infrastructure

| Category | Technology |
|---|---|
| Container | Docker |
| Orchestration (GCP) | GKE (Google Kubernetes Engine) |
| Orchestration (Azure) | AKS (Azure Kubernetes Service) |
| CI/CD | GitHub Actions |
| Object storage (GCP) | Google Cloud Storage (GCS) |
| Object storage (Azure) | Azure Blob Storage |
| Relational DB | PostgreSQL 16 (self-hosted in K8s) |
| Vector DB | Qdrant (self-hosted in K8s) |
| Cache | Redis 7 (self-hosted in K8s) |
| DNS / CDN / DDoS | Cloudflare |
| Container registry | Google Artifact Registry (GCP) / Azure Container Registry (Azure) |
| Secrets | Kubernetes Secrets + cloud secret manager |
| Monitoring | Prometheus + Grafana |
| Log aggregation | Loki + Grafana |
| GPU | NVIDIA A100 / T4 (GCP) |

---

## 27. Database Strategy

### PostgreSQL — Relational Data

Self-hosted in Kubernetes — identical deployment on GCP and Azure. One database instance, multiple schemas per module:

| Schema | Module | Key Tables |
|---|---|---|
| `auth` | Shared | users, sessions, oauth_accounts, otp_codes |
| `chatbot` | Medical Chatbot | chat_sessions, chat_messages |
| `drug_agent` | Drug Agent | drug_sessions, export_history |
| `symptom_alpha` | Symptom Checker Alpha | symptom_sessions, symptom_results |
| `symptom_beta` | Symptom Checker Beta | beta_sessions, beta_review_queue, beta_consents, beta_training_runs |
| `lab_test` | Lab Test Explainer | lab_sessions, lab_results |
| `research` | Research Paper | research_sessions, papers, analyses |
| `admin` | Admin Panel | admin_users, audit_logs |

### Qdrant — Vector Database

Self-hosted in Kubernetes. Collections per module knowledge base:

| Collection | Module | Embedding Model |
|---|---|---|
| `minilm_drugs` | Drug Agent | all-MiniLM-L6-v2 |
| `pubmedbert_drugs` | Drug Agent | PubMedBERT |
| `minilm_medical` | Medical Chatbot | all-MiniLM-L6-v2 |
| `minilm_labs` | Lab Test Explainer | all-MiniLM-L6-v2 |
| `minilm_research` | Research Paper | all-MiniLM-L6-v2 |

### Redis — Cache & Session Store

| Key Pattern | TTL | Contents |
|---|---|---|
| `session:{id}` | 1–2 hours | Active session state (all modules) |
| `progress:{id}` | Pub/Sub | WebSocket progress events |
| `rxnorm:{hash}` | 24h | RxNorm normalization results |
| `drug_profile:{rxcui}` | 12h | Drug profile LLM results |
| `interaction:{a}:{b}` | 12h | Drug pair interaction results |
| `condition:{id}:{age}` | 24h | Infermedica condition details |
| `triage_label:{level}:{lang}` | 24h | LLM triage summaries |
| `web_scrape:{hash}` | 6h | Cached Playwright scrape results |
| `rag_result:{hash}` | 6h | Cached RAG retrieval results |

---

## 28. Caching Strategy — Redis

All modules follow the **cache-aside pattern**:

```python
# app/shared/cache/cache_service.py
class CacheService:
    async def get_or_set(self, key: str, fetch_fn, ttl: int) -> dict:
        cached = await self.redis.get(key)
        if cached:
            logger.info("cache_hit", key=key)
            return json.loads(cached)

        result = await fetch_fn()
        await self.redis.setex(key, ttl, json.dumps(result))
        logger.info("cache_miss_and_set", key=key, ttl=ttl)
        return result
```

Cache keys are always deterministic — based on content hashes or canonical identifiers (RxCUIs, not raw drug names) to maximize hit rates.

---

## 29. Storage Strategy

### Object Storage Abstraction

A storage abstraction layer handles the GCS/Azure Blob difference transparently:

```python
# app/shared/storage/storage_service.py
class StorageService:
    def __init__(self):
        if settings.CLOUD == "gcp":
            self.backend = GCSBackend(settings.GCS_BUCKET)
        elif settings.CLOUD == "azure":
            self.backend = AzureBlobBackend(settings.AZURE_CONTAINER)

    async def upload(self, path: str, data: bytes) -> str:
        return await self.backend.upload(path, data)

    async def download(self, path: str) -> bytes:
        return await self.backend.download(path)
```

Setting `CLOUD=gcp` or `CLOUD=azure` in `.env` switches the backend. No other code changes.

### What is Stored

| Storage Path | Contents |
|---|---|
| `models/` | Fine-tuned model weights, LoRA adapters |
| `exports/{user_id}/` | User-generated PDF/DOCX/TXT exports |
| `uploads/{session_id}/` | User-uploaded PDFs (Research Paper module) |
| `training/datasets/` | JSONL fine-tuning datasets |
| `training/runs/` | Training run artifacts, evaluation reports |

---

# PART 6 — DEPLOYMENT

---

## 30. Deployment Overview — GCP + Azure

MAISYS uses a two-environment deployment strategy:

| Environment | Cloud | Purpose | Status |
|---|---|---|---|
| **Testing / Simulation** | GCP | Full production simulation, GPU testing, concurrency load testing, fine-tuning runs | $300 free credits |
| **Production** | Azure | Live user-facing deployment | $200 free credits → paid |
| **Future** | AWS | Optional third cloud | ~$100 free credits (TBD) |

Both environments use **identical Kubernetes manifests** — the only differences are cloud-specific values (storage bucket names, container registry URLs, GPU node types) injected via environment variables and Kubernetes ConfigMaps.

---

## 31. GCP — Testing & Simulation Environment

### 31.1 Purpose

The GCP environment is a full production simulation, not just a dev environment. It runs the complete MAISYS stack with GPU — the goal is to validate:
- End-to-end pipeline correctness across all modules
- LangGraph agent behavior under load
- vLLM model serving performance and latency
- Concurrency under pressure (load testing)
- Fine-tuning pipeline (LoRA training runs)
- WebSocket stability under concurrent sessions
- Redis and PostgreSQL performance under real query patterns

### 31.2 GCP Services Used

| Service | Purpose | Cost Tier |
|---|---|---|
| **GKE** (Google Kubernetes Engine) | Container orchestration | Standard cluster |
| **GPU Node Pool** | vLLM serving + fine-tuning | NVIDIA T4 or A100 |
| **Cloud Storage (GCS)** | Model weights, exports, training data | Per GB |
| **Artifact Registry** | Docker image storage | Per GB |
| **Cloud DNS** | DNS for test subdomains | Per zone |
| **Cloud Load Balancer** | Ingress for GKE | Per rule |

### 31.3 GKE Cluster Layout

```
GKE Cluster (single region: us-central1)
│
├── Node Pool: cpu-pool (e2-standard-4)
│   ├── maisys-app (FastAPI backend)
│   ├── maisys-frontend (React)
│   ├── maisys-admin (Admin panel)
│   ├── postgres (self-hosted)
│   ├── redis (self-hosted)
│   └── qdrant (self-hosted)
│
└── Node Pool: gpu-pool (n1-standard-8 + T4 GPU)
    ├── vllm-server (model inference)
    └── finetune-job (LoRA training — runs as K8s Job)
```

### 31.4 Load Testing Plan

Tools: **k6** or **Locust** for HTTP load testing + **Artillery** for WebSocket load testing

Test scenarios:
- 50 concurrent Symptom Checker sessions (multi-turn)
- 100 concurrent Drug Agent interaction checks
- 20 concurrent Research Paper parallel analyses
- WebSocket stability: 200 simultaneous connections
- vLLM throughput: requests/second under sustained load
- Redis cache hit rate under load
- PostgreSQL connection pool exhaustion test

---

## 32. Azure — Production Environment

### 32.1 Azure Services Used

| Service | Purpose |
|---|---|
| **AKS** (Azure Kubernetes Service) | Container orchestration |
| **Azure Blob Storage** | Model weights, exports, uploads |
| **Azure Container Registry** | Docker image storage |
| **Azure DNS** | Production DNS |
| **Azure Load Balancer** | Ingress for AKS |
| **Azure Key Vault** | Secrets management |
| **Azure Monitor** | Metrics + alerting |
| **GPU VM / Node Pool** | vLLM serving (NC-series) |

### 32.2 AKS Cluster Layout

```
AKS Cluster (production region)
│
├── System Node Pool (Standard_D4s_v3)
│   ├── maisys-app
│   ├── maisys-frontend
│   ├── maisys-admin
│   ├── postgres
│   ├── redis
│   └── qdrant
│
└── GPU Node Pool (Standard_NC6s_v3 — V100)
    └── vllm-server
```

---

## 33. Cloud Portability — Switching Between Clouds

Cloud switching requires **zero code changes**. All cloud-specific values are externalized:

### What Changes Between Clouds

| Component | GCP Value | Azure Value |
|---|---|---|
| Object storage class | `GCSBackend` | `AzureBlobBackend` |
| Storage bucket/container | `BUCKET=maisys-gcp` | `CONTAINER=maisys-azure` |
| Container registry | `gcr.io/maisys/...` | `maisys.azurecr.io/...` |
| GPU node type | `nvidia-tesla-t4` | `Standard_NC6s_v3` |
| Secret manager | GCP Secret Manager | Azure Key Vault |
| `CLOUD` env var | `gcp` | `azure` |

### Kubernetes Manifest Strategy

Base manifests in `k8s/base/` — identical for all clouds.
Cloud-specific overlays in `k8s/overlays/gcp/` and `k8s/overlays/azure/` using Kustomize:

```
k8s/
├── base/
│   ├── app-deployment.yaml
│   ├── postgres-statefulset.yaml
│   ├── redis-statefulset.yaml
│   ├── qdrant-statefulset.yaml
│   └── vllm-deployment.yaml
├── overlays/
│   ├── gcp/
│   │   ├── kustomization.yaml    ← patches GCS, GKE GPU, Artifact Registry
│   │   └── configmap-gcp.yaml
│   └── azure/
│       ├── kustomization.yaml    ← patches Azure Blob, AKS GPU, ACR
│       └── configmap-azure.yaml
```

Deploy to GCP: `kubectl apply -k k8s/overlays/gcp/`
Deploy to Azure: `kubectl apply -k k8s/overlays/azure/`

---

## 34. Kubernetes Architecture

### 34.1 Core Deployments

```yaml
# k8s/base/app-deployment.yaml (simplified)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: maisys-app
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: maisys-app
        image: maisys/app:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: maisys-config
        - secretRef:
            name: maisys-secrets
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
```

### 34.2 Persistent Storage (PostgreSQL, Redis, Qdrant)

All stateful services use `StatefulSet` with `PersistentVolumeClaim`:

```yaml
# PostgreSQL StatefulSet uses:
storageClassName: standard-rwo   # GCP
# or
storageClassName: managed-premium # Azure
```

### 34.3 GPU Node Scheduling

```yaml
# vllm-deployment.yaml GPU node selector
nodeSelector:
  cloud.google.com/gke-accelerator: nvidia-tesla-t4   # GCP
  # or
  accelerator: nvidia-v100                             # Azure
tolerations:
- key: nvidia.com/gpu
  operator: Exists
  effect: NoSchedule
resources:
  limits:
    nvidia.com/gpu: 1
```

---

## 35. CI/CD Pipeline — GitHub Actions

### 35.1 Pipeline Flow

```
Developer pushes to GitHub
        ↓
GitHub Actions triggered
        ↓
┌──────────────────────────────┐
│  Job 1: Test                 │
│  - pytest (unit + integration│
│  - Frontend type check       │
│  - Lint (ruff + eslint)      │
└──────────────┬───────────────┘
               ↓ (on pass)
┌──────────────────────────────┐
│  Job 2: Build                │
│  - Docker build (backend)    │
│  - Docker build (frontend)   │
│  - Docker build (admin)      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│  Job 3: Push                 │
│  - Push to Artifact Registry │
│    (GCP) or ACR (Azure)      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│  Job 4: Deploy               │
│  main branch → GCP (testing) │
│  release tag → Azure (prod)  │
│  kubectl apply -k overlays/  │
└──────────────────────────────┘
```

### 35.2 GitHub Actions Workflow

```yaml
# .github/workflows/deploy.yml
name: MAISYS CI/CD

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run backend tests
        run: pytest tests/ -v --cov=app
      - name: Run frontend type check
        run: cd frontend && npx tsc --noEmit

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Build and push to GCP Artifact Registry
        if: github.ref == 'refs/heads/main'
        run: |
          gcloud auth configure-docker us-central1-docker.pkg.dev
          docker build -t us-central1-docker.pkg.dev/maisys/app:$GITHUB_SHA .
          docker push us-central1-docker.pkg.dev/maisys/app:$GITHUB_SHA

  deploy-gcp:
    needs: build-and-push
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to GKE
        run: |
          gcloud container clusters get-credentials maisys-cluster
          kubectl apply -k k8s/overlays/gcp/
          kubectl set image deployment/maisys-app app=$IMAGE_TAG

  deploy-azure:
    needs: build-and-push
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to AKS
        run: |
          az aks get-credentials --resource-group maisys --name maisys-cluster
          kubectl apply -k k8s/overlays/azure/
          kubectl set image deployment/maisys-app app=$IMAGE_TAG
```

---

## 36. Environment Configuration

### 36.1 Core `.env` Variables

```env
# Cloud
CLOUD=gcp                          # gcp | azure | aws

# LLM
LLM_MODEL=gpt-4o                   # any LiteLLM model string
LLM_EXTRACTION_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=...

# Local model serving (vLLM)
VLLM_BASE_URL=http://vllm-server:8000/v1
VLLM_MODEL_NAME=meditron-7b

# Infermedica (Symptom Checker Alpha)
INFERMEDICA_APP_ID=...
INFERMEDICA_APP_KEY=...

# RxNorm (Drug Agent — public, no key)
RXNORM_BASE_URL=https://rxnav.nlm.nih.gov/REST

# Web search (Tier 2 fallback)
SERPER_API_KEY=...

# STT
SUPERTONE_API_KEY=...

# Two-tier retrieval thresholds
MIN_RAG_CHUNKS=3
MIN_LLM_CONFIDENCE=0.75

# Databases
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/maisys
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333

# Storage (GCP)
GCS_BUCKET=maisys-storage
GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-sa.json

# Storage (Azure)
AZURE_STORAGE_CONNECTION_STRING=...
AZURE_CONTAINER=maisys-storage

# Auth
SECRET_KEY=...
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# App
ENVIRONMENT=production             # development | staging | production
```

---

# PART 7 — OPERATIONS

---

## 37. Monitoring & Observability

### 37.1 Monitoring Stack

| Tool | Purpose |
|---|---|
| **Prometheus** | Metrics collection (request rates, latency, error rates, GPU utilization) |
| **Grafana** | Dashboards for all metrics |
| **Loki** | Log aggregation |
| **Grafana Alerting** | Alerts for error spikes, latency degradation, GPU OOM |

### 37.2 Key Metrics per Module

**Platform-wide:**
- Request rate per module (req/min)
- P50/P95/P99 latency per endpoint
- Error rate (4xx, 5xx)
- Cache hit rate (Redis)
- Active WebSocket connections

**LLM / AI:**
- LLM call latency (cloud vs local)
- LLM token usage per call
- vLLM GPU utilization and memory usage
- RAG retrieval latency
- Tier 1 vs Tier 2 retrieval ratio (how often fallback triggers)

**Symptom Checker:**
- Sessions started / completed / abandoned
- Average turns per session
- Triage level distribution
- Emergency detections per day

**Beta:**
- Beta sessions per day
- GP review queue depth
- Model evaluation accuracy over time
- Fine-tuning run history

### 37.3 Grafana Dashboards

1. **Platform Overview** — all modules, request rates, error rates
2. **AI Performance** — LLM latency, vLLM GPU, RAG tier ratios
3. **Symptom Checker** — session metrics, triage distribution
4. **Beta Training** — dataset growth, GP review queue, model accuracy
5. **Infrastructure** — Kubernetes node health, pod restarts, storage usage

---

## 38. Logging Strategy

All services use `structlog` for structured JSON logging. Every log entry includes: `timestamp`, `level`, `service`, `module`, `session_id` (where applicable), `user_id` (hashed), `duration_ms`.

```python
# Consistent logging pattern across all modules
logger.info("agent_step_complete",
    module="drug_agent",
    step="rag_retrieval",
    session_id=session_id,
    chunks_returned=8,
    tier="tier1",
    duration_ms=245
)

logger.warning("tier2_triggered",
    module="drug_agent",
    reason="low_chunk_count",
    chunk_count=2,
    drug_names=["warfarin", "aspirin"]
)

logger.error("llm_generation_failed",
    module="symptom_checker",
    step="rephrase_question",
    model=settings.LLM_MODEL,
    error=str(exc)
)
```

Logs shipped to Loki via Promtail sidecar on each pod.

---

## 39. Rate Limiting & Timeouts

### 39.1 Rate Limits (per IP, per minute)

| Endpoint Category | Limit |
|---|---|
| Session start (all modules) | 10/min |
| Conversation turns | 30/min |
| Export generation | 5/min |
| Drug lookup / profile | 20/min |
| Brand/generic converter | 30/min |
| Admin endpoints | 60/min |
| Auth endpoints | 5/min (brute force protection) |

### 39.2 Timeout Matrix

| Operation | Timeout |
|---|---|
| RxNorm API | 5s |
| Infermedica API calls | 10–15s |
| RAG retrieval (Qdrant) | 8s |
| Sufficiency evaluation (LLM) | 15s |
| Playwright scrape (Drugs.com) | 20s |
| Web search (SerpAPI) | 15s |
| LLM generation (cloud) | 45s |
| LLM generation (vLLM local) | 120s |
| LangGraph agent pipeline | 90s |
| Export generation | 30s |
| STT transcription | 30s |

---

## 40. Scaling Strategy

### 40.1 Horizontal Pod Autoscaling (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: maisys-app-hpa
spec:
  scaleTargetRef:
    name: maisys-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### 40.2 Scaling Considerations per Component

| Component | Scaling Strategy |
|---|---|
| FastAPI app | HPA on CPU — horizontal |
| vLLM server | Vertical (more GPU VRAM) first, then horizontal replicas |
| Redis | Redis Cluster for high concurrency |
| PostgreSQL | Read replicas for analytics queries |
| Qdrant | Qdrant distributed mode for large collections |
| WebSocket connections | Sticky sessions via Ingress annotation |

---

## 41. Backup & Recovery

| Component | Backup Strategy | Frequency | Retention |
|---|---|---|---|
| PostgreSQL | `pg_dump` → GCS/Azure Blob | Daily | 30 days |
| Qdrant | Qdrant snapshot API → object storage | Weekly | 4 snapshots |
| Redis | RDB snapshot + AOF | Hourly RDB, continuous AOF | 7 days |
| Model weights | Stored in object storage (immutable) | Per training run | All versions |
| Training datasets | Versioned JSONL in object storage | Per training run | All versions |

---

# PART 8 — SECURITY & COMPLIANCE

---

## 42. Security Architecture

### 42.1 Authentication & Authorization

- **JWT tokens** (HS256, 24h expiry) for user sessions
- **Refresh tokens** (7-day expiry, rotated on use)
- **OTP** (6-digit, 10-minute expiry) for registration and sensitive account changes
- **OAuth 2.0** (Google, Apple) — tokens never stored, only user profile
- **Admin auth** — separate JWT issuer, separate secret key, IP allowlist
- **Role-based access**: `user`, `beta_user`, `gp_reviewer`, `admin`

### 42.2 API Security

- All endpoints behind HTTPS (Cloudflare TLS termination)
- Rate limiting on all endpoints (slowapi)
- CORS configured: only `app.maisys.x` and `admin.maisys.x` allowed
- Request size limits: 10MB max body (PDF uploads: 50MB separate endpoint)
- SQL injection: prevented by SQLAlchemy ORM (no raw SQL)
- XSS: React escapes all output by default; Content-Security-Policy header set
- CSRF: JWT-based auth (stateless) — no session cookies, CSRF not applicable

### 42.3 Secrets Management

- **Development**: `.env` files (never committed to git)
- **GCP**: Google Secret Manager → mounted as Kubernetes Secrets
- **Azure**: Azure Key Vault → mounted as Kubernetes Secrets
- API keys, database passwords, JWT secrets — never in code or Docker images
- Secret rotation: quarterly or immediately on suspected compromise

### 42.4 Network Security

```
Internet → Cloudflare (DDoS + WAF) → Load Balancer → Kubernetes Ingress
                                                              ↓
                                                    Only ports 80/443 exposed
                                                    Internal services: ClusterIP only
                                                    Database ports: not exposed externally
```

---

## 43. Data Privacy & User Data Handling

### 43.1 What Data MAISYS Collects

| Data Type | Stored | Purpose | Retention |
|---|---|---|---|
| Email address | Yes (hashed for lookups) | Auth, OTP | Account lifetime |
| Password | Yes (bcrypt hashed) | Auth | Account lifetime |
| Age + sex | Yes (per session) | Module functionality | Session + 90 days |
| Symptom descriptions | Yes (per session) | Module functionality, history | 90 days |
| Session results | Yes | History, export | 90 days |
| Beta sessions (consented) | Yes (anonymized) | Model training | Until consent withdrawn |
| IP addresses | Logs only | Rate limiting, security | 30 days |
| OAuth tokens | Never stored | — | — |

### 43.2 User Rights

Users can at any time:
- Export all their data (JSON download from settings)
- Delete their account and all associated data
- Withdraw Beta consent — stops future collection and flags existing data for exclusion
- View what data has been collected (transparency page)

### 43.3 Data Minimization

- No data is collected that isn't needed for functionality
- Age and sex are stored per-session, not as permanent profile fields
- Free-text symptom descriptions are not linked to identifiable user profile fields in Beta storage

---

## 44. HIPAA Considerations

MAISYS is designed with HIPAA-aligned practices, though full HIPAA certification depends on deployment context and applicable regulations:

### 44.1 Technical Safeguards Applied

| Safeguard | Implementation |
|---|---|
| **Encryption at rest** | PostgreSQL: pgcrypto for sensitive fields; GCS/Azure Blob: server-side encryption enabled |
| **Encryption in transit** | TLS 1.3 on all connections (Cloudflare + internal K8s mTLS) |
| **Access controls** | Role-based access, minimum privilege, admin audit logs |
| **Audit logging** | All admin actions logged with user ID, timestamp, action |
| **Automatic logoff** | JWT expiry (24h), frontend session timeout (30min inactivity) |
| **Unique user IDs** | Each user has UUID — no shared accounts |

### 44.2 Important Disclaimer

MAISYS is an informational tool, not a clinical system. It does not store Protected Health Information (PHI) as defined by HIPAA in the clinical sense — it stores user-submitted symptom descriptions which are not medical records. However, MAISYS applies HIPAA-aligned technical practices as a baseline of responsible data handling.

Organizations deploying MAISYS in a clinical context should conduct a formal HIPAA risk assessment and may need to execute a Business Associate Agreement (BAA) with cloud providers.

---

## 45. Beta Data & Consent Compliance

### 45.1 Consent Requirements

All three consent gates must be completed before Beta access:
1. Explicit informed consent screen (cannot be skipped)
2. Account settings opt-in (default OFF)
3. Onboarding flow confirmation (3 steps)

All consent events are timestamped and stored in PostgreSQL with the consent form version shown.

### 45.2 Anonymization Standards

Before any Beta session data enters the review queue:
- User ID replaced with SHA-256 hash (irreversible)
- PII removed: names, phone numbers, emails (regex + NLP)
- Dates shifted ±30 days (prevents temporal re-identification)
- Geographic identifiers below city level removed

### 45.3 GP Reviewer Data Access

GP reviewers see only anonymized records. They cannot see the original user ID, access the user's other sessions, or export data outside the review interface.

### 45.4 Consent Withdrawal

On withdrawal: Beta access revoked immediately, no new sessions collected, existing data in training pipeline flagged for exclusion on next training run, withdrawal timestamp recorded.

---

# PART 9 — ROADMAP

---

## 46. What's Built

| Module / Component | Status |
|---|---|
| Medical Chatbot | ✅ Guide complete — ready to build |
| Drug Agent | ✅ Guide complete (CrewAI) — LangGraph migration needed |
| Symptom Checker Alpha | ✅ Guide complete — ready to build |
| Symptom Checker Beta | ✅ Guide complete — ready to build |
| Lab Test Explainer | ✅ Guide complete — ready to build |
| Research Paper Assistant | ✅ Guide complete — ready to build |
| LangGraph unified agent architecture | ✅ Decided — documented |
| Two-tier retrieval system | ✅ Documented |
| Bilingual Arabic/English architecture | ✅ Documented |
| GCP/Azure deployment strategy | ✅ Documented — K8s manifests to build |
| CI/CD pipeline | ✅ GitHub Actions workflow documented |
| Frontend 28-page structure | ✅ Defined |
| Domain & subdomain structure | ✅ Defined — purchase pending |
| Model catalogue | ✅ BioMistral, Meditron-7B, MedMO-8B-Next documented |

---

## 47. What's Next

### Immediate — Build Phase

1. Migrate Drug Agent from CrewAI → LangGraph
2. Build LangGraph shared tool layer (`app/shared/tools/`)
3. Set up GCP GKE cluster — deploy full stack to GCP testing environment
4. Run load tests — concurrency simulation, WebSocket stability, vLLM throughput
5. Build Symptom Checker Alpha — Infermedica + LLM hybrid
6. Deploy vLLM on GCP GPU node — test with Meditron-7B
7. Build Beta data ingestion pipeline — all format extractors
8. Build GP review dashboard (admin panel)
9. Purchase domain — maisys.org or maisys.cloud via Cloudflare
10. Set up CI/CD — GitHub Actions → GKE

### Near-Term — Polish Phase

11. Frontend build — all 28 pages in React + TypeScript
12. Supertone STT integration — Medical Chatbot voice input
13. First Beta fine-tuning run — when 500+ GP-approved records accumulated
14. Azure production deployment — migrate from GCP testing to Azure production
15. Performance optimization — based on GCP load test results
16. Arabic language QA — full bilingual testing across all modules

---

## 48. Future Vision

### Short-Term (6–12 months)
- All 6 modules live and serving real users
- Beta Symptom Checker with first fine-tuned model deployed
- Continuous GP review loop running
- Full Arabic + English UX across all modules

### Medium-Term (12–24 months)
- Beta model graduates — fine-tuned LLM reaches Alpha quality gates and becomes an alternative engine alongside Infermedica
- Arabic fine-tuning — MedMO-8B-Next fine-tuned on Arabic-translated GP-reviewed dataset
- Voice-first mode — full STT + TTS conversational interface for Symptom Checker and Chatbot
- Mobile apps — React Native iOS and Android
- MAISYS public API for developers and healthcare organizations

### Long-Term (2+ years)
- MAISYS becomes infrastructure — the fine-tuned medical LLM powers all modules, removing dependency on third-party APIs
- Specialized fine-tuned models per module — drug interactions, lab tests, research papers
- Clinical partnerships — integrate with hospital systems for pre-consultation screening
- Regulatory pathway — CE marking or FDA clearance exploration
- Expand language support — French, Turkish, Swahili based on user demand

---

# PART 10 — MASTER CHECKLIST

---

## 49. Platform-Wide Implementation Checklist

### Shared Infrastructure
- [ ] `app/shared/tools/` — all 7 shared LangGraph tool nodes
- [ ] `app/shared/llm/unified_client.py` — LiteLLM + confidence scoring
- [ ] `app/shared/cache/cache_service.py`
- [ ] `app/shared/storage/storage_service.py` — GCS/Azure abstraction
- [ ] `app/shared/translation/translation_service.py`
- [ ] `app/shared/export/export_service.py` — TXT/DOCX/PDF Arabic RTL
- [ ] `app/shared/safety/safety_service.py` — emergency detection AR+EN
- [ ] `app/shared/stt/supertone_client.py`
- [ ] WebSocket progress handler shared across all modules

### Authentication
- [ ] Email + password + bcrypt hashing
- [ ] JWT + refresh token rotation
- [ ] OTP (email + phone)
- [ ] Google OAuth + Apple OAuth
- [ ] Email verification + password reset flows
- [ ] Admin auth (separate JWT + IP allowlist)
- [ ] Roles: user, beta_user, gp_reviewer, admin

### LangGraph Agents
- [ ] Drug Agent: migrate from CrewAI → LangGraph
- [ ] Medical Chatbot: LangGraph graph
- [ ] Symptom Checker Alpha: LangGraph + Infermedica nodes
- [ ] Lab Test Explainer: LangGraph graph
- [ ] Research Paper: LangGraph graph (parallel execution)
- [ ] All agents use shared tool nodes
- [ ] Human-in-loop `interrupt()` for emergency triage + drug contraindication
- [ ] `.astream_events()` → WebSocket progress for all modules

### GCP Testing Environment
- [ ] GKE cluster (us-central1)
- [ ] CPU + GPU (T4) node pools
- [ ] All K8s manifests deployed
- [ ] vLLM running Meditron-7B on GPU
- [ ] GCS bucket + storage service connected
- [ ] GitHub Actions → GKE working
- [ ] End-to-end test: register → use all modules → export
- [ ] Load test: 50 concurrent Symptom Checker sessions
- [ ] Load test: 100 concurrent Drug Agent interactions
- [ ] WebSocket load test: 200 simultaneous connections
- [ ] vLLM throughput benchmark recorded

### Azure Production Environment
- [ ] AKS cluster + GPU node pool
- [ ] Azure Kustomize overlays applied
- [ ] Azure Blob + Key Vault connected
- [ ] GitHub Actions → AKS release deployment
- [ ] SSL active on all subdomains
- [ ] Azure Monitor configured

### Domain & DNS
- [ ] Domain purchased (maisys.org or maisys.cloud)
- [ ] Cloudflare DNS — all 9 subdomains configured
- [ ] Wildcard SSL (`*.maisys.x`) active
- [ ] HTTP → HTTPS redirect
- [ ] DDoS protection enabled

### Frontend — All 28 Pages
- [ ] Public: Landing, About, How It Works, Contact, Privacy, Terms
- [ ] Auth: Login, Register, Forgot/Reset Password, OTP Verification, Email Verification
- [ ] Dashboard: Main, Profile, Security, History, Saved, Beta Consent
- [ ] Modules: Chatbot, Drug Agent, Symptom Alpha, Symptom Beta, Lab Test, Research
- [ ] Admin: Login, GP Review, System Monitoring, User Management, Model Tracker
- [ ] Arabic RTL layout working across all pages
- [ ] Light + Dark mode toggle
- [ ] WebSocket progress bar on all module pages

### Monitoring
- [ ] Prometheus scraping all pods
- [ ] Grafana dashboards: Platform, AI Performance, Symptom Checker, Beta, Infrastructure
- [ ] Alerting: error spikes, LLM latency, GPU OOM, pod crashes
- [ ] Loki log aggregation

### Security
- [ ] HTTPS everywhere
- [ ] CORS configured (allowed origins only)
- [ ] Rate limiting active
- [ ] JWT secrets in Kubernetes Secrets
- [ ] Bcrypt password hashing
- [ ] Admin IP allowlist
- [ ] Audit log for admin actions
- [ ] Security review before production launch

### Beta System
- [ ] Triple consent (all 3 gates)
- [ ] Consent withdrawal
- [ ] Data ingestion pipeline (5 format extractors)
- [ ] Anonymization (PII removal + date shift + ID hash)
- [ ] GP review dashboard
- [ ] JSONL dataset builder
- [ ] LoRA fine-tuning script (PEFT + TRL)
- [ ] Model evaluator
- [ ] vLLM Beta server (separate from Alpha)
- [ ] First fine-tuning run at 500+ GP-approved records
- [ ] Retraining: 200+ new records OR monthly

### Backup & Recovery
- [ ] PostgreSQL daily backup → object storage
- [ ] Qdrant weekly snapshot
- [ ] Redis RDB + AOF
- [ ] Backup restoration tested

---

*MAISYS — Master Project Guide*
*Platform: Modular Monolith | LangGraph Agents | LiteLLM | Two-Tier RAG | Infermedica | vLLM*
*Deployment: GCP (testing) → Azure (production) | GitHub Actions CI/CD | Kubernetes*
*Languages: Arabic + English | Models: BioMistral-7B / Meditron-7B / MedMO-8B-Next | STT: Supertone*
