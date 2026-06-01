# MAISYS — Technical Development Guide
## Part 6: Design Patterns · Code Style · Agent Pattern · Testing · ORM · Pydantic Layers

---

## Table of Contents

1. [Design Patterns Catalogue](#1-design-patterns-catalogue)
2. [Code Style and Standards](#2-code-style-and-standards)
3. [Agent Pattern — How LangGraph Graphs Are Written](#3-agent-pattern--how-langgraph-graphs-are-written)
4. [ORM Choice and Pattern](#4-orm-choice-and-pattern)
5. [Pydantic Models — How Many Layers and What Each Does](#5-pydantic-models--how-many-layers-and-what-each-does)
6. [Dependency Injection Pattern](#6-dependency-injection-pattern)
7. [Exception Hierarchy and Error Handling Pattern](#7-exception-hierarchy-and-error-handling-pattern)
8. [Testing Pattern](#8-testing-pattern)
9. [Configuration Pattern](#9-configuration-pattern)
10. [Health Check Pattern](#10-health-check-pattern)

---

## 1. Design Patterns Catalogue

These are the patterns used throughout MAISYS. Every developer working on any service should know them. When you are unsure how to implement something, check here first — there is almost always an established pattern already in use.

### Repository Pattern

**Where:** Every service — `repository/postgres_repo.py`, `repository/cache_repo.py`, `repository/qdrant_repo.py`

**Rule:** All database and cache access — every SQLAlchemy query, every Redis call, every Qdrant search — lives in the repository layer. Service functions never call SQLAlchemy directly. Service functions never call Redis directly.

**Why:** Repository functions are the only place that knows the database schema. If the schema changes, only the repository changes. Services are insulated from persistence details. Repositories are also the easiest layer to mock in tests.

**Pattern:**
```
Service calls repo method with clean domain objects
→ Repository translates to SQL / Redis command
→ Returns clean domain objects or raises RepositoryException
```

---

### Service Layer Pattern (Orchestrator)

**Where:** Every service — `services/main_service.py` and sub-services

**Rule:** Business logic lives only in the service layer. Routes call one service method. Services call repositories and external clients. Services never return ORM objects to routes — they return Pydantic response models.

**A service method does exactly this:**
1. Receive validated input (Pydantic schema from route)
2. Coordinate: call repositories, call shared services, call agents
3. Apply business rules
4. Return a Pydantic response schema

Services are always async. Services never import from other services directly — they make REST calls via httpx.

---

### Strategy Pattern

**Where:** OCR engine selection, NLP tool mode selection (model vs LLM), translation provider selection, STT/TTS provider selection

**Rule:** When there are multiple interchangeable implementations of the same operation, use a selector that returns the correct implementation at runtime based on configuration. The caller does not know which implementation is active.

**Pattern:**
```
engine_selector.py
→ reads config (PRIMARY_OCR_ENGINE env var)
→ returns PaddleOCRWrapper | MistralOCRWrapper | LightOnOCRWrapper | LLMOCRWrapper
→ caller calls .extract(file_bytes) regardless of which engine was selected
```

All strategies implement the same interface (same method names, same parameter types, same return type). Adding a new strategy means adding a new class and one entry in the selector — nothing else changes.

---

### Factory Pattern

**Where:** LLM client creation in `shared/llm_client/client.py`, storage backend in `shared/storage/storage_client.py`

**Rule:** Object construction that depends on configuration belongs in a factory. The rest of the codebase uses the result of the factory — never constructing these objects directly.

**LLM client factory:** Called at service startup. Reads active model config from model-router-service. Returns a configured LiteLLM client. When the admin switches models, the next request fetches a new config and the factory creates a new client. The service code that calls `llm_client.generate()` is unchanged.

**Storage factory:** Reads `CLOUD` env var. Returns `GCSBackend` or `AzureBlobBackend`. Caller calls `storage.upload(path, data)` — unaware of which backend is active.

---

### Cache-Aside Pattern

**Where:** `repository/cache_repo.py` in every service, `shared/llm_client/kv_cache_manager.py`

**Rule:** Check cache first. On miss: fetch from primary source, write to cache, return. On hit: return cached value without touching primary source.

```
async def get_drug_profile(rxcui: str) -> DrugProfile:
    cache_key = f"drug_profile:{rxcui}"
    cached = await cache_repo.get(cache_key)
    if cached:
        return DrugProfile.model_validate_json(cached)
    profile = await drug_repo.fetch_from_qdrant(rxcui)
    await cache_repo.set(cache_key, profile.model_dump_json(), ttl=43200)
    return profile
```

Cache keys are always deterministic and based on canonical identifiers (RxCUIs, not raw drug names, session UUIDs not user emails). A different input that resolves to the same canonical ID hits the same cache entry.

---

### Circuit Breaker Pattern

**Where:** `shared/llm_client/client.py` (for LLM calls), inter-service HTTP calls in all services

**Rule:** After N consecutive failures to a downstream service within a time window, stop calling it and return a fallback immediately. Re-probe after a recovery period.

**States:** Closed (normal — calls pass through) → Open (failing — all calls return fallback immediately) → Half-Open (recovery probe — one test call allowed).

**Parameters used in MAISYS:**
- Failure threshold before opening: 5 consecutive failures
- Time window: 30 seconds
- Recovery probe interval: 60 seconds
- On open: LLM calls switch to local fallback model. Service calls return structured error immediately.

---

### Observer Pattern (Progress Events)

**Where:** `shared/progress/publisher.py`, WebSocket handlers in all services

**Rule:** Agents and services publish events. They do not know who is listening. The WebSocket handler subscribes and forwards to browsers. Other subscribers (monitoring, logging) can be added without touching the publisher.

Agents call `await progress_publisher.emit(session_id, event)` after each node. The publisher writes to Redis pub/sub channel `progress:{session_id}`. WebSocket handlers subscribe at session start and unsubscribe at session end.

---

### Adapter Pattern

**Where:** `shared/storage/storage_client.py`, `shared/embedding/dual_embedder.py`

**Rule:** When an external system has an incompatible interface, wrap it in an adapter that exposes the interface the rest of the codebase expects.

GCS and Azure Blob have completely different SDKs. The `GCSBackend` and `AzureBlobBackend` adapters both implement `StorageInterface` with `upload(path, data)` and `download(path)` methods. All services call the interface — never the SDK directly.

---

### Singleton Pattern

**Where:** Embedding models, vLLM client, Playwright browser context pool

**Rule:** Objects that are expensive to initialize and safe to share across requests are initialized once at startup and reused.

Embedding models (MiniLM, PubMedBERT) are loaded into memory once in the service's `lifespan` startup event and stored as module-level singletons. All RAG requests use the same model instance. This avoids 2–5 second model loading delay per request.

Playwright browser contexts are pooled. The pool is initialized at startup with `PLAYWRIGHT_POOL_SIZE` instances. Requests acquire a context from the pool, use it, and return it. If all contexts are in use, the request waits (with a timeout).

---

### Idempotency Pattern

**Where:** Export job creation, paper ingestion, Beta session submission

**Rule:** Repeating the same operation should produce the same result without side effects. Critical for operations triggered via RabbitMQ (which may deliver messages more than once).

Export jobs check for an existing job with the same `(source_session_id, format, user_id)` combination before creating a new one. If one exists and is complete, return the existing result. If one exists and is queued/processing, return its status. Only create a new job if none exists.

Paper ingestion checks `papers.doi` before downloading. If a paper with the same DOI already exists in the session, skip download and ingestion.

---

## 2. Code Style and Standards

### Python Version

Python 3.11 minimum. All services use 3.11+ features: `match` statements for routing, `tomllib` for config, `ExceptionGroup` for concurrent error handling, improved `asyncio` performance.

### Formatting and Linting

**Black** — code formatter. Applied automatically. Line length: 88 characters. No debates about style — Black decides.

**isort** — import sorter. Profile: Black-compatible. Import order: stdlib → third-party → local (shared) → service-local. Each group separated by a blank line.

**ruff** — linter. Replaces flake8, pydocstyle, and many others. Runs in CI on every commit. All ruff warnings are errors — zero warnings permitted in merged code.

Both Black and ruff run as pre-commit hooks. They also run as the first step in every GitHub Actions pipeline. A commit that fails formatting check does not build.

### Type Hints

Type hints are required on every function signature — parameters and return type. No `Any` type except in the shared error handler where it is explicitly justified. No implicit `Optional` — use `X | None` (Python 3.10+ union syntax).

Typed dicts are used for structured dictionaries. JSONB fields in the database are typed as `dict[str, Any]` at the ORM level but immediately parsed into typed Pydantic models at the repository level before being returned to the service.

### Async Conventions

All service functions are `async def`. All repository functions are `async def`. All route handlers are `async def`. Synchronous code that blocks (local ML model inference, some PDF processing) is wrapped in `asyncio.get_event_loop().run_in_executor(executor, sync_fn, *args)` with a pre-configured `ThreadPoolExecutor`.

Never use `time.sleep()` in async code — always `await asyncio.sleep()`. Never use `requests` library in async code — always `httpx.AsyncClient`.

### Naming Conventions

**Files:** `snake_case.py` — `session_service.py`, `drug_repo.py`, `rxnorm_client.py`

**Classes:** `PascalCase` — `DrugSessionService`, `RxNormClient`, `InteractionAgent`

**Functions and methods:** `snake_case` — `get_drug_profile`, `normalize_drug_names`, `emit_progress_event`

**Constants:** `UPPER_SNAKE_CASE` — `MAX_CONCURRENT_PAIRS`, `DEFAULT_CACHE_TTL`

**Pydantic models (schemas):** `PascalCase` with suffix indicating purpose — `DrugInteractionRequest`, `DrugInteractionResponse`, `DrugSessionCreate`

**SQLAlchemy ORM models:** `PascalCase` matching the table concept — `DrugSession`, `ChatMessage`, `LabTest`

**Private functions:** `_leading_underscore` for functions not intended to be called outside their module — `_normalize_text`, `_build_query`

### Docstrings

All public functions have docstrings. Private functions (`_leading_underscore`) have docstrings if their purpose is non-obvious. Format:

```python
async def get_drug_profile(rxcui: str, language: str = "en") -> DrugProfileResponse:
    """Retrieve a complete drug profile from the Drug RAG knowledge base.

    Searches both drug_minilm and drug_pubmedbert Qdrant collections.
    Falls back to web search if RAG returns insufficient results.

    Args:
        rxcui: RxNorm Concept Unique Identifier for the drug.
        language: Response language ('en' or 'ar'). Defaults to 'en'.

    Returns:
        DrugProfileResponse with all profile fields populated.

    Raises:
        DrugNotFoundException: If the drug cannot be found in RAG or via web fallback.
        RAGRetrievalError: If Qdrant is unavailable and cache is empty.
    """
```

### Import Organization

```python
# 1. Standard library
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

# 2. Third-party
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# 3. Shared library
from shared.error_handler.exceptions import ServiceUnavailableError
from shared.logger.logger import get_logger
from shared.progress.publisher import ProgressPublisher

# 4. Service-local
from .repository.drug_repo import DrugRepository
from .models.schemas import DrugProfileRequest, DrugProfileResponse
from .services.normalization_service import NormalizationService
```

---

## 3. Agent Pattern — How LangGraph Graphs Are Written

### 3.1 State Definition

Every agent starts with a typed state class. State fields are grouped by purpose. Required fields have no default. Optional fields have typed defaults.

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class InteractionAgentState(TypedDict):
    # Input fields — set at graph start, never modified
    drug_a_rxcui: str
    drug_b_rxcui: str
    drug_a_name: str
    drug_b_name: str
    session_id: str
    trace_id: str
    language: str

    # Retrieval fields — set by retrieval node
    rag_chunks: list[dict]
    rag_chunk_count: int
    rag_sufficient: bool
    llm_confidence: float

    # Web fallback fields — set by web search node if triggered
    web_content: str | None
    web_source_url: str | None

    # Result fields — set by analysis node
    severity: str | None           # major / moderate / minor / contraindicated
    mechanism: str | None
    recommendation: str | None
    source_tier: str | None        # local / web

    # Control fields — managed by the graph engine
    iterations: int
    error: dict | None             # {"node": "...", "type": "...", "recoverable": bool}
    token_budget_remaining: int
```

All state fields use simple Python types (str, int, bool, list, dict) or None. No Pydantic models in state — state must be serializable for LangGraph's checkpointing. If you need a Pydantic model, convert to dict before storing in state.

### 3.2 Node Structure

Every node follows the same structure without exception:

```python
async def rag_retrieval_node(state: InteractionAgentState) -> dict:
    """Retrieve drug interaction chunks from Drug RAG for the given pair."""
    # 1. Check control fields first
    if state["error"] and not state["error"]["recoverable"]:
        return {}  # Terminal error — skip this node, graph routes to terminal

    if state["iterations"] >= MAX_ITERATIONS:
        return {"error": {"node": "rag_retrieval", "type": "MaxIterationsReached", "recoverable": False}}

    # 2. Publish start event
    await progress_publisher.emit(state["session_id"], {
        "event": "node_start",
        "agent_name": "InteractionAgent",
        "node_name": "rag_retrieval",
        "input_summary": f"Searching DRUG INTERACTIONS for {state['drug_a_name']} + {state['drug_b_name']}"
    })

    start_time = time.monotonic()

    try:
        # 3. Do the actual work — with timeout
        async with asyncio.timeout(NODE_TIMEOUTS["rag_retrieval"]):
            chunks = await dual_embedder.search(
                query=f"{state['drug_a_name']} {state['drug_b_name']} drug interaction",
                collections=["drug_minilm", "drug_pubmedbert"],
                filters={"section_name": "DRUG INTERACTIONS",
                         "drug_name": [state["drug_a_name"], state["drug_b_name"]]},
                top_k=8
            )

        # 4. Validate output
        if not isinstance(chunks, list):
            raise ValueError("RAG search returned unexpected type")

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # 5. Publish complete event
        await progress_publisher.emit(state["session_id"], {
            "event": "node_complete",
            "agent_name": "InteractionAgent",
            "node_name": "rag_retrieval",
            "duration_ms": duration_ms,
            "output_summary": f"{len(chunks)} chunks retrieved",
            "tokens_used": 0
        })

        # 6. Return only the fields this node is responsible for updating
        return {
            "rag_chunks": chunks,
            "rag_chunk_count": len(chunks),
            "iterations": state["iterations"] + 1
        }

    except asyncio.TimeoutError:
        await _emit_error_event(state, "rag_retrieval", "QdrantTimeout", will_retry=True)
        return {
            "error": {"node": "rag_retrieval", "type": "QdrantTimeout",
                      "message": "RAG search timed out", "recoverable": True},
            "iterations": state["iterations"] + 1
        }
    except Exception as exc:
        await _emit_error_event(state, "rag_retrieval", type(exc).__name__, will_retry=False)
        return {
            "error": {"node": "rag_retrieval", "type": type(exc).__name__,
                      "message": str(exc), "recoverable": False},
            "iterations": state["iterations"] + 1
        }
```

### 3.3 Conditional Edge Function

```python
def route_after_sufficiency(state: InteractionAgentState) -> str:
    """Route to generation or web fallback based on sufficiency evaluation."""
    if state.get("error") and not state["error"]["recoverable"]:
        return "terminal"
    if state["rag_sufficient"]:
        return "generate_result"
    else:
        return "web_fallback"
```

Edge functions always handle the error state case first. They return string node names that match exactly the names used in `graph.add_node()`.

### 3.4 Graph Assembly

```python
from langgraph.graph import StateGraph, END

def build_interaction_graph() -> StateGraph:
    graph = StateGraph(InteractionAgentState)

    # Add all nodes
    graph.add_node("rag_retrieval", rag_retrieval_node)
    graph.add_node("sufficiency_eval", sufficiency_eval_node)
    graph.add_node("web_fallback", web_fallback_node)
    graph.add_node("generate_result", generate_result_node)
    graph.add_node("terminal", terminal_node)

    # Entry point
    graph.set_entry_point("rag_retrieval")

    # Sequential edges
    graph.add_edge("rag_retrieval", "sufficiency_eval")

    # Conditional edge
    graph.add_conditional_edges(
        "sufficiency_eval",
        route_after_sufficiency,
        {
            "generate_result": "generate_result",
            "web_fallback": "web_fallback",
            "terminal": "terminal"
        }
    )

    graph.add_edge("web_fallback", "generate_result")
    graph.add_edge("generate_result", END)
    graph.add_edge("terminal", END)

    return graph.compile()

# Build once at module level — reused for all requests
INTERACTION_GRAPH = build_interaction_graph()
```

### 3.5 Running a Graph

The orchestrator initializes state and runs the compiled graph:

```python
async def run_interaction_agent(
    drug_a: NormalizedDrug,
    drug_b: NormalizedDrug,
    session_id: str,
    language: str
) -> InteractionResult:

    initial_state = InteractionAgentState(
        drug_a_rxcui=drug_a.rxcui,
        drug_b_rxcui=drug_b.rxcui,
        drug_a_name=drug_a.canonical_name,
        drug_b_name=drug_b.canonical_name,
        session_id=session_id,
        trace_id=str(uuid.uuid4()),
        language=language,
        rag_chunks=[],
        rag_chunk_count=0,
        rag_sufficient=False,
        llm_confidence=0.0,
        web_content=None,
        web_source_url=None,
        severity=None,
        mechanism=None,
        recommendation=None,
        source_tier=None,
        iterations=0,
        error=None,
        token_budget_remaining=TOKEN_BUDGETS["interaction"]
    )

    try:
        async with asyncio.timeout(GRAPH_TIMEOUT_SECONDS):
            final_state = await INTERACTION_GRAPH.ainvoke(initial_state)
    except asyncio.TimeoutError:
        # Graph-level timeout — return whatever partial state is available
        return InteractionResult(
            severity="unknown",
            error="Analysis timed out — partial results only"
        )

    # Map final state to result object
    if final_state.get("error") and not final_state["error"]["recoverable"]:
        return InteractionResult(error=final_state["error"]["message"])

    return InteractionResult(
        severity=final_state["severity"],
        mechanism=final_state["mechanism"],
        recommendation=final_state["recommendation"],
        source_tier=final_state["source_tier"]
    )
```

---

## 4. ORM Choice and Pattern

### 4.1 SQLAlchemy 2.0 — Async Mode

All services use SQLAlchemy 2.0 with the async session (`AsyncSession`) and async engine (`create_async_engine`). The `asyncpg` driver is used for PostgreSQL — it is the fastest async PostgreSQL driver available for Python.

Never use SQLAlchemy 1.x patterns (`.query()`, implicit session, `db.session`). Always use SQLAlchemy 2.0 patterns (`select()`, `async with AsyncSession() as session`).

### 4.2 ORM Model Definition

All ORM models inherit from a shared `Base` class defined in `shared/models/base.py`. The Base uses `DeclarativeBase` with `MappedColumn` annotations (SQLAlchemy 2.0 style).

```python
# shared/models/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

```python
# services/drug-service/models/domain.py
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column, relationship
from shared.models.base import Base

class DrugSession(Base):
    __tablename__ = "drug_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    feature: Mapped[str] = mapped_column(String(30), nullable=False)
    input_drugs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    web_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )
```

### 4.3 Session Management

Sessions are created per-request using FastAPI dependency injection. The session is opened at the start of the request and committed (or rolled back) at the end.

```python
# services/drug-service/main.py — database setup
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    settings.DRUG_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,          # Verify connections are alive before use
    pool_recycle=3600            # Recycle connections every hour
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
```

```python
# shared/auth/dependencies.py — reusable session dependency
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

The session is injected into repository functions via FastAPI `Depends()`. Repositories never create their own sessions.

### 4.4 Repository Function Pattern

```python
# services/drug-service/repository/drug_repo.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from .domain import DrugSession

class DrugRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(self, user_id: uuid.UUID, feature: str,
                              input_drugs: list[dict]) -> DrugSession:
        record = DrugSession(
            user_id=user_id,
            feature=feature,
            input_drugs=input_drugs
        )
        self.session.add(record)
        await self.session.flush()  # Get the generated ID without committing
        return record

    async def update_result(self, session_id: uuid.UUID, result: dict,
                             source_tier: str, web_sources: list[dict] | None) -> None:
        stmt = (
            update(DrugSession)
            .where(DrugSession.id == session_id)
            .values(result=result, source_tier=source_tier, web_sources=web_sources)
        )
        await self.session.execute(stmt)

    async def get_user_sessions(self, user_id: uuid.UUID,
                                 limit: int = 20, offset: int = 0) -> list[DrugSession]:
        stmt = (
            select(DrugSession)
            .where(DrugSession.user_id == user_id)
            .order_by(desc(DrugSession.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

### 4.5 Avoiding N+1 Queries

When loading related objects, always use SQLAlchemy's `selectinload` or `joinedload` to eager-load relationships in one query — never rely on lazy loading in async mode (lazy loading does not work with async sessions).

```python
from sqlalchemy.orm import selectinload

# Load lab session with all its tests in two queries (not N+1)
stmt = (
    select(LabSession)
    .options(selectinload(LabSession.tests))
    .where(LabSession.id == session_id)
)
```

### 4.6 Transaction Boundaries

Transactions are managed at the service layer, not the repository layer. A service method that writes to multiple tables wraps all writes in a single transaction by using the same session for all repository calls.

The session is committed once per request by the `get_db_session` dependency. If any exception is raised during the request, the session is rolled back automatically.

---

## 5. Pydantic Models — How Many Layers and What Each Does

MAISYS uses three distinct Pydantic model layers. Each layer has a specific purpose and a specific place in the codebase. Models do not cross their layer boundaries.

### Layer 1 — Request Schemas

**Location:** `models/schemas.py` in each service — classes named with `Request` suffix

**Purpose:** Validate and parse incoming HTTP request bodies. These are what FastAPI binds to route handler parameters.

**Rules:**
- All fields have explicit types and validation rules
- Optional fields have explicit defaults or `None`
- Validators (`@field_validator`) enforce business constraints (age must be 0–120, drug name must be non-empty, file type must be in allowed set)
- Request schemas are never returned to the client
- Request schemas never contain database IDs (except in URL path parameters)
- Field aliases used to accept both `camelCase` (from JS frontend) and `snake_case`

```python
class DrugInteractionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    drug_names: list[str] = Field(..., min_length=2, max_length=10,
                                   description="2–10 drug names to check for interactions")
    language: Literal["en", "ar"] = Field(default="en")
    user_profile: UserProfileContext | None = Field(default=None)

    @field_validator("drug_names")
    @classmethod
    def validate_drug_names(cls, v: list[str]) -> list[str]:
        cleaned = [name.strip() for name in v if name.strip()]
        if len(cleaned) < 2:
            raise ValueError("At least 2 non-empty drug names are required")
        if len(set(name.lower() for name in cleaned)) < 2:
            raise ValueError("Drug names must be distinct")
        return cleaned
```

---

### Layer 2 — Response Schemas

**Location:** `models/schemas.py` in each service — classes named with `Response` suffix

**Purpose:** Define the exact shape of data returned to the client. These are what FastAPI serializes to JSON in route responses and what services return.

**Rules:**
- All fields have explicit types
- Never include internal implementation details (database IDs for internal records, raw SQL errors, stack traces)
- Always include `success: bool` at the top level (from the standard envelope in `shared/error_handler/responses.py`)
- Nested response objects are their own schema classes (not raw dicts)
- Response schemas use `model_config = ConfigDict(from_attributes=True)` when they need to be built from ORM objects

```python
class DrugPairInteractionResult(BaseModel):
    drug_a: str
    drug_b: str
    severity: Literal["contraindicated", "major", "moderate", "minor"]
    severity_color: str
    mechanism: str
    clinical_significance: str
    recommendation: str
    high_risk_populations: list[str]
    source_tier: Literal["local", "web"]
    source_label: str
    citations: list[CitationSchema]

class DrugInteractionResponse(BaseModel):
    session_id: uuid.UUID
    normalized_drugs: list[NormalizedDrugSchema]
    pairs: list[DrugPairInteractionResult]
    overall_risk: str
    overall_risk_color: str
    overall_summary: str
    duplicate_warnings: list[str]
    disclaimer: str
    total_tokens_used: int | None = None
```

---

### Layer 3 — Internal / Domain Transfer Objects

**Location:** `models/schemas.py` — classes without a specific suffix, or in `models/internal.py`

**Purpose:** Carry data between service functions, between service and repository, and between service and agent orchestrator. These are internal types — never exposed to the API surface.

**Rules:**
- Used when a simple dict would be untyped and unsafe
- Used when the same structured data flows through multiple functions
- Smaller and simpler than request/response schemas — only the fields needed for the specific internal flow
- Not validated with strict validators (data is already trusted coming from internal sources)

```python
class NormalizedDrug(BaseModel):
    """Internal representation of a drug after RxNorm normalization."""
    original_name: str
    canonical_name: str
    rxcui: str
    active_ingredients: list[str]
    duplicate_flag: bool

class RagChunk(BaseModel):
    """A single chunk returned from Qdrant search."""
    chunk_id: str
    text: str
    score: float
    drug_name: str | None = None
    section_name: str | None = None
    source: str
    url: str | None = None
    chunk_type: Literal["text", "table"] = "text"

class AgentResult(BaseModel):
    """Generic container for agent execution output."""
    success: bool
    data: dict | None = None
    error_message: str | None = None
    source_tier: Literal["local", "web"] | None = None
    tokens_used: int = 0
```

---

### The Mapping Pattern (ORM → Response)

ORM models are SQLAlchemy objects returned by the repository. They must be converted to response schemas before leaving the service layer. The conversion uses Pydantic's `model_validate` with `from_attributes=True`:

```python
# In service layer — never in route or repository
orm_session = await drug_repo.get_session(session_id)
response = DrugSessionResponse.model_validate(orm_session)
return response
```

For complex cases where ORM field names differ from response field names, use `Field(alias=...)` or a custom `model_validator` that maps fields explicitly.

JSONB database fields (stored as `dict` in ORM) are parsed back into typed schemas using `model_validate`:

```python
# JSONB field 'result' in ORM is a dict — parse it into typed schema
result_schema = DrugInteractionResponse.model_validate(orm_session.result)
```

---

## 6. Dependency Injection Pattern

FastAPI's `Depends()` system is used throughout MAISYS. It manages session lifecycle, authentication, and service instantiation. Dependencies are composable — a dependency can depend on other dependencies.

### Standard Dependencies Per Route

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from shared.auth.dependencies import get_current_user, require_role
from shared.auth.dependencies import get_db_session
from .repository.drug_repo import DrugRepository
from .services.drug_info_service import DrugInfoService

router = APIRouter(prefix="/drug", tags=["drug"])

def get_drug_repo(session: AsyncSession = Depends(get_db_session)) -> DrugRepository:
    return DrugRepository(session)

def get_drug_service(repo: DrugRepository = Depends(get_drug_repo)) -> DrugInfoService:
    return DrugInfoService(repo)

@router.post("/profile", response_model=APIResponse[DrugProfileResponse])
async def get_drug_profile(
    body: DrugProfileRequest,
    service: DrugInfoService = Depends(get_drug_service),
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    result = await service.get_profile(
        drug_name=body.drug_name,
        user_id=current_user.id,
        language=body.language
    )
    return APIResponse(success=True, data=result)
```

### Authentication Dependencies

```python
# shared/auth/dependencies.py

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    http_client: httpx.AsyncClient = Depends(get_http_client)
) -> AuthenticatedUser:
    """Validate JWT by calling auth-service /auth/validate endpoint."""
    response = await http_client.post(
        f"{settings.AUTH_SERVICE_URL}/auth/validate",
        json={"token": token},
        timeout=3.0
    )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    data = response.json()["data"]
    return AuthenticatedUser(
        id=uuid.UUID(data["user_id"]),
        role=data["role"],
        email_verified=data["email_verified"]
    )

def require_role(*allowed_roles: str):
    """Factory for role-checking dependencies."""
    async def check_role(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return check_role

# Usage:
@router.post("/admin/switch-model")
async def switch_model(admin: AuthenticatedUser = Depends(require_role("admin"))):
    ...
```

---

## 7. Exception Hierarchy and Error Handling Pattern

### Base Hierarchy

All service-specific exceptions extend from the shared base classes. This allows the global error handler to catch all MAISYS exceptions and map them to appropriate HTTP responses.

```python
# shared/error_handler/exceptions.py

class MAISYSException(Exception):
    """Base class for all MAISYS application exceptions."""
    http_status: int = 500
    error_code: str = "INTERNAL_ERROR"
    user_message: str = "An unexpected error occurred. Please try again."

class ValidationError(MAISYSException):
    http_status = 422
    error_code = "VALIDATION_ERROR"

class NotFoundError(MAISYSException):
    http_status = 404
    error_code = "NOT_FOUND"

class UnauthorizedError(MAISYSException):
    http_status = 401
    error_code = "UNAUTHORIZED"

class ForbiddenError(MAISYSException):
    http_status = 403
    error_code = "FORBIDDEN"

class ServiceUnavailableError(MAISYSException):
    http_status = 503
    error_code = "SERVICE_UNAVAILABLE"
    user_message = "This service is temporarily unavailable. Please try again shortly."

class RateLimitError(MAISYSException):
    http_status = 429
    error_code = "RATE_LIMIT_EXCEEDED"
```

```python
# services/drug-service/exceptions/exceptions.py

from shared.error_handler.exceptions import NotFoundError, ServiceUnavailableError, MAISYSException

class DrugNotFoundException(NotFoundError):
    error_code = "DRUG_NOT_FOUND"
    def __init__(self, drug_name: str):
        self.user_message = f"Could not find '{drug_name}'. Please check the spelling or try the generic name."
        super().__init__(self.user_message)

class RxNormAPIError(ServiceUnavailableError):
    error_code = "RXNORM_UNAVAILABLE"
    user_message = "Drug name lookup is temporarily unavailable. Please try again in a moment."

class RAGRetrievalError(MAISYSException):
    http_status = 503
    error_code = "RAG_UNAVAILABLE"
    user_message = "The medical knowledge base is temporarily unavailable."

class DrugInteractionAgentError(MAISYSException):
    http_status = 500
    error_code = "AGENT_ERROR"
    user_message = "Drug interaction analysis encountered an error. Partial results may be available."
```

### Global Exception Handler

```python
# shared/error_handler/handlers.py

def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(MAISYSException)
    async def maisys_exception_handler(request: Request, exc: MAISYSException):
        logger.warning("application_error",
            error_code=exc.error_code,
            error_type=type(exc).__name__,
            path=request.url.path)
        return JSONResponse(
            status_code=exc.http_status,
            content={"success": False, "error": exc.user_message, "error_code": exc.error_code}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Convert Pydantic validation errors to user-friendly messages
        first_error = exc.errors()[0]
        field = " → ".join(str(loc) for loc in first_error["loc"])
        message = f"Invalid value for '{field}': {first_error['msg']}"
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": message, "error_code": "VALIDATION_ERROR"}
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        # Log full exception with traceback, but never expose it to the client
        logger.error("unhandled_exception", error=str(exc), exc_info=True,
                     path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "An unexpected error occurred.",
                     "error_code": "INTERNAL_ERROR"}
        )
```

### Rule: Never Expose Internals

The global handler ensures no internal detail ever reaches the client response. Specifically prohibited in any response body: stack traces, database error messages, SQL query text, internal object IDs, file system paths, API keys (obviously), service-to-service HTTP details, and Qdrant/Redis connection errors.

---

## 8. Testing Pattern

### 8.1 Test Structure Per Service

```
services/{service_name}/tests/
├── conftest.py              ← fixtures shared across all tests
├── test_routes.py           ← HTTP endpoint tests (request/response)
├── test_services.py         ← business logic tests (service functions)
├── test_repository.py       ← repository function tests (with test DB)
├── test_agents.py           ← LangGraph agent tests
└── test_utils.py            ← utility function tests
```

### 8.2 Test Database

Tests use a real PostgreSQL database (not SQLite — SQLite does not support PostgreSQL-specific types like JSONB and UUID). A separate test database is created for each test run and destroyed after.

The `conftest.py` at the service root:
```python
# tests/conftest.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

TEST_DATABASE_URL = "postgresql+asyncpg://test:test@localhost:5432/maisys_drug_test"

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(test_engine):
    """Provides a transactional test session that rolls back after each test."""
    async with test_engine.begin() as conn:
        session = AsyncSession(bind=conn)
        yield session
        await session.rollback()
        await session.close()
```

Using a transaction per test that rolls back means each test starts with a clean database — no test data leaks between tests. This is faster than truncating tables.

### 8.3 Mocking External Services

All external HTTP calls (Infermedica, RxNorm, SerpAPI, Drugs.com, LLM providers) are mocked in tests. Never make real API calls in tests.

```python
# Using pytest-httpx for httpx mocking
import pytest
from pytest_httpx import HTTPXMock

@pytest.mark.asyncio
async def test_rxnorm_normalization_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://rxnav.nlm.nih.gov/REST/rxcui.json?name=aspirin&search=1",
        json={"idGroup": {"rxnormId": ["1191"]}}
    )
    httpx_mock.add_response(
        url="https://rxnav.nlm.nih.gov/REST/rxcui/1191/property.json?propName=RxNorm+Name",
        json={"propConceptGroup": {"propConcept": [{"propValue": "aspirin"}]}}
    )

    client = RxNormClient()
    result = await client.normalize("aspirin")
    assert result.rxcui == "1191"
    assert result.canonical_name == "aspirin"

@pytest.mark.asyncio
async def test_rxnorm_api_down_uses_cache(httpx_mock: HTTPXMock, redis_mock):
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
    redis_mock.set("rxnorm:aspirin_hash", '{"rxcui": "1191", "canonical_name": "aspirin"}')

    client = RxNormClient()
    result = await client.normalize("aspirin")
    assert result.rxcui == "1191"  # Got from cache despite API being down
```

### 8.4 Mocking LLM Calls

LLM calls are mocked to return structured test responses. This makes LLM-dependent tests deterministic and fast.

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_drug_profile_generation():
    mock_llm_response = DrugProfileResponse(
        drug_name="aspirin",
        canonical_name="aspirin",
        rxcui="1191",
        drug_class="Salicylates / NSAIDs",
        mechanism_of_action="Inhibits COX-1 and COX-2 enzymes...",
        ...
    )

    with patch("services.drug_info_service.llm_client.generate",
               new_callable=AsyncMock,
               return_value=mock_llm_response.model_dump_json()):
        service = DrugInfoService(repo=mock_repo)
        result = await service.get_profile("aspirin", language="en")
        assert result.drug_class == "Salicylates / NSAIDs"
```

### 8.5 Agent Testing

LangGraph agents are tested by providing a known initial state and asserting on the final state. External tool calls within agent nodes are mocked.

```python
@pytest.mark.asyncio
async def test_interaction_agent_tier1_success(mock_qdrant, mock_progress_publisher):
    """Test that agent returns Tier 1 result when RAG is sufficient."""
    mock_qdrant.return_value = [
        RagChunk(text="Warfarin and aspirin interaction: major bleeding risk...",
                 score=0.89, section_name="DRUG INTERACTIONS", ...)
        # ... 5 chunks total (above MIN_CHUNKS threshold)
    ]

    initial_state = InteractionAgentState(
        drug_a_rxcui="11289", drug_b_rxcui="1191",
        drug_a_name="warfarin", drug_b_name="aspirin",
        session_id="test-session", trace_id="test-trace",
        language="en", rag_chunks=[], rag_chunk_count=0,
        rag_sufficient=False, llm_confidence=0.0,
        web_content=None, web_source_url=None,
        severity=None, mechanism=None, recommendation=None,
        source_tier=None, iterations=0, error=None,
        token_budget_remaining=2000
    )

    final_state = await INTERACTION_GRAPH.ainvoke(initial_state)

    assert final_state["source_tier"] == "local"
    assert final_state["severity"] in ["major", "moderate", "minor", "contraindicated"]
    assert final_state["error"] is None
    assert final_state["iterations"] <= MAX_ITERATIONS

@pytest.mark.asyncio
async def test_interaction_agent_max_iterations_stops_graph(mock_qdrant_timeout):
    """Test that agent stops cleanly when max iterations reached."""
    # mock_qdrant_timeout simulates Qdrant always timing out
    final_state = await INTERACTION_GRAPH.ainvoke(initial_state_with_iterations_at_limit)
    # Graph must not loop — must reach END node
    assert final_state["error"] is not None
    assert final_state["iterations"] <= MAX_ITERATIONS
```

### 8.6 Route Tests

Route tests use FastAPI's `AsyncClient` to test the full HTTP layer including authentication.

```python
@pytest.mark.asyncio
async def test_drug_interaction_requires_auth(async_client: AsyncClient):
    response = await async_client.post("/drug/interaction/drug-drug",
                                        json={"drug_names": ["aspirin", "warfarin"]})
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"

@pytest.mark.asyncio
async def test_drug_interaction_validates_min_drugs(auth_async_client: AsyncClient):
    response = await auth_async_client.post("/drug/interaction/drug-drug",
                                             json={"drug_names": ["aspirin"]})  # Only 1 drug
    assert response.status_code == 422
    assert "at least 2" in response.json()["error"].lower()
```

### 8.7 Coverage Targets

| Layer | Target Coverage | Notes |
|---|---|---|
| Utils (pure functions) | 95% | Pure functions are easy to test completely |
| Repository functions | 80% | Test happy path + key error paths |
| Service functions | 85% | Test all branches including error handling |
| Agent nodes | 80% | Test happy path, timeout, unrecoverable error |
| Route handlers | 75% | Test auth, validation, success, and main error cases |
| **Overall per service** | **80%** | Enforced in CI — build fails below this |

Coverage checked by `pytest-cov` in CI. Reports uploaded to the monitoring dashboard.

---

## 9. Configuration Pattern

### 9.1 Settings Class Per Service

Each service has a `Settings` class using pydantic-settings. This reads from environment variables, validates them at startup, and provides type-safe access throughout the service.

```python
# services/drug-service/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class DrugServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # Database
    drug_database_url: str
    drug_redis_url: str

    # RAG
    qdrant_url: str
    drug_rag_collection_minilm: str = "drug_minilm"
    drug_rag_collection_pubmedbert: str = "drug_pubmedbert"
    rag_top_k: int = 8
    min_rag_chunks: int = 3
    min_llm_confidence: float = 0.75

    # Agent limits
    interaction_agent_max_iterations: int = 5
    agent_graph_timeout_seconds: int = 90
    max_concurrent_pairs: int = 5

    # Environment
    environment: str = "production"
    log_level: str = "INFO"

    @field_validator("min_llm_confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("min_llm_confidence must be between 0.0 and 1.0")
        return v

# Singleton — instantiated once at module load
settings = DrugServiceSettings()
```

The `settings` object is imported wherever configuration is needed. It is never passed as a parameter (it's a singleton). Test environments override values by setting environment variables before importing.

### 9.2 Fail Fast on Missing Config

If a required environment variable (one without a default) is not set, the settings class raises a `ValidationError` at import time — before the service starts accepting requests. This is intentional: a service with missing critical configuration should not start. The error message from pydantic-settings clearly identifies which variable is missing.

---

## 10. Health Check Pattern

Every service exposes two health endpoints. The API Gateway checks these before routing traffic. Kubernetes liveness and readiness probes use these endpoints.

### 10.1 Liveness Check (`/health/live`)

**Purpose:** Is the process alive? Can it accept connections?
**Does:** Returns 200 immediately. No database check. No external calls.
**Used by:** Kubernetes liveness probe. If this fails, Kubernetes restarts the pod.

```python
@app.get("/health/live")
async def liveness():
    return {"status": "alive", "service": settings.SERVICE_NAME}
```

### 10.2 Readiness Check (`/health/ready`)

**Purpose:** Is the service ready to handle production traffic?
**Does:** Checks all critical dependencies: database connection, Redis connection, Qdrant connection (for RAG services), model-router-service reachability.
**Used by:** Kubernetes readiness probe. If this fails, the pod is removed from the load balancer (stops receiving traffic) but is not restarted.

```python
@app.get("/health/ready")
async def readiness():
    checks: dict[str, str] = {}
    all_healthy = True

    # Database
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        all_healthy = False

    # Redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
        all_healthy = False

    # Qdrant (for RAG services only)
    if HAS_QDRANT:
        try:
            await qdrant_client.get_collections()
            checks["qdrant"] = "ok"
        except Exception as exc:
            checks["qdrant"] = f"error: {type(exc).__name__}"
            all_healthy = False

    status_code = 200 if all_healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_healthy else "not_ready",
                 "service": settings.SERVICE_NAME,
                 "checks": checks}
    )
```

### 10.3 Startup Sequence

Every service `main.py` follows the same startup sequence using FastAPI's lifespan context manager:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    logger.info("service_starting", service=settings.SERVICE_NAME)

    # 1. Run database migrations
    await run_alembic_migrations()

    # 2. Initialize database connection pool
    await init_database()

    # 3. Initialize Redis connection
    await init_redis()

    # 4. Load singleton models (embedding models, etc.)
    await init_models()       # MiniLM, PubMedBERT — blocking but runs once

    # 5. Initialize Playwright browser pool (if applicable)
    if HAS_PLAYWRIGHT:
        await init_playwright_pool()

    # 6. Verify readiness
    health = await check_all_dependencies()
    if not health["all_ok"]:
        raise RuntimeError(f"Service not ready: {health['failures']}")

    logger.info("service_ready", service=settings.SERVICE_NAME)

    yield  # Service is running

    # === SHUTDOWN ===
    logger.info("service_stopping", service=settings.SERVICE_NAME)
    await close_database()
    await close_redis()
    if HAS_PLAYWRIGHT:
        await close_playwright_pool()
    logger.info("service_stopped", service=settings.SERVICE_NAME)

app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)
```

---

*MAISYS Technical Development Guide — Part 6: Design Patterns · Code Style · Agent Pattern · Testing · ORM · Pydantic Layers*

*This is the final part. The complete MAISYS Technical Development Guide spans Parts 1–6.*

*Summary of coverage:*
*Part 1 — Platform Overview · Microservices Architecture · Services Catalog · Shared Library · Model Registry · CI/CD*
*Part 2 — Data Collection · Extraction · Chunking · RAG Knowledge Base*
*Part 3 — Agent Architecture · Production Reliability · All Module Services in Full Detail*
*Part 4 — Beta Training Pipeline · Frontend · Deployment · Operations · Security · Master Checklist*
*Part 5 — Database Schemas · API Contracts · Safety Service · Auth Service · Notification Service · Frontend Detail · Environment Variables*
*Part 6 — Design Patterns · Code Style · Agent Pattern · Testing · ORM · Pydantic Layers*
