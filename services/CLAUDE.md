# services/ — All-Services Standards

Every service in this folder follows the same internal architecture and conventions. Per-service CLAUDE.md files inherit from this and add only what's specific.

## Layered Architecture

Every service has exactly these layers:

```
services/<service-name>/
├── main.py                    FastAPI app entrypoint, mounts routes, sets up middleware
├── routes/                    HTTP/WebSocket endpoints — thin layer, parse input, delegate
├── services/                  Business logic — the heart of the service
├── repository/                Data access — SQLAlchemy queries, Qdrant calls, no business logic
├── models/                    SQLAlchemy ORM + Pydantic schemas
├── utils/                     Pure helper functions, no I/O
├── exceptions/                Service-specific exception classes (extend shared/error_handler base)
├── tests/                     pytest tests mirroring the layer structure
├── Dockerfile
├── requirements.txt
└── alembic/                   Per-service migrations (when the service has a database)
    └── versions/
```

**The layering rule:** dependencies flow `routes → services → repository`. Never the reverse, never skipping layers. `routes/` doesn't touch the database; `repository/` doesn't contain business decisions.

## Required Patterns

### Async everywhere

All I/O is `async`. Database, HTTP, file I/O, queue, cache. No synchronous blocking calls in the request path. If you find yourself reaching for `requests`, you want `httpx.AsyncClient`. If you find yourself reaching for `time.sleep`, you want `asyncio.sleep`.

### Dependency injection via FastAPI

Services receive their dependencies through FastAPI's `Depends()` system. No global singletons. No service-locator patterns. No module-level connection pools used directly inside business logic.

```python
async def get_repository(session: AsyncSession = Depends(get_db_session)) -> DrugRepository:
    return DrugRepository(session)

@router.get("/drugs/{drug_id}")
async def get_drug(drug_id: int, repo: DrugRepository = Depends(get_repository)):
    return await repo.get_by_id(drug_id)
```

### Repository pattern

Database access is the repository's job, full stop. Business logic never writes SQL or composes Qdrant queries. The repository exposes methods like `get_drug_by_rxnorm()`, not `execute_query()`.

### Pydantic for everything that crosses a boundary

- Request bodies: Pydantic v2 models in `models/schemas.py`
- Response bodies: Pydantic v2 models, wrapped in `APIResponse` from `shared/error_handler`
- LLM tool calls: Pydantic models, validated before dispatch
- WebSocket events: Pydantic models, serialized to JSON

### Errors via the global handler

Raise typed exceptions from `exceptions/`. The global handler (set up in `main.py` via `shared/error_handler`) converts them to the right HTTP response. Never `raise HTTPException(...)` from business logic — only at the route boundary if absolutely needed.

### Logging via structlog

Use the configured `structlog` logger from `shared/logger`. Bind request-scoped context (`request_id`, `user_id`, `service`) at middleware level — don't pass them down through function arguments.

```python
from shared.logger import get_logger
logger = get_logger(__name__)

logger.info("drug.lookup.started", drug_name=drug_name, user_id=user_id)
```

## Required Reading Before Implementing a Service

Before opening any service-specific Claude Code session, read:

- `docs/technical-guides/part3.md` (the section for your specific service)
- `docs/technical-guides/part5.md` (the schema for your service)
- `docs/technical-guides/part6.md` (relevant design patterns — usually §3 agent, §5 LLM client, §7 error handling)

## Testing Standard

- Every public function in `services/` has at least one unit test
- Every endpoint in `routes/` has an integration test
- Every repository method has a test against a real Postgres (via `pytest-postgresql`) or mocked
- Coverage target: 80% on `services/` and `repository/`, 100% on critical paths (auth, safety, billing)
- Tests live in `tests/` mirroring source structure

## What Goes Where

| Code type | Lives in |
|---|---|
| HTTP route handler | `routes/` |
| WebSocket route handler | `routes/websockets.py` or `routes/ws_<name>.py` |
| Business decision / agent / orchestration | `services/` |
| Database query | `repository/` |
| External API call (e.g., RxNorm) | `repository/external/` or `services/<feature>/clients/` (case-by-case) |
| Pydantic schema | `models/schemas.py` |
| SQLAlchemy model | `models/db.py` |
| LLM prompt template | `services/<feature>/prompts.py` |
| Helper utility (pure, no I/O) | `utils/` |

## What's NEVER in a Service

- Cross-service imports (`from services.drug_service import ...`). Services talk via HTTP/RPC, never via Python imports.
- Direct cloud SDK calls (use `shared/storage` instead).
- Direct LLM provider calls (use `shared/llm_client` instead).
- Synchronous I/O.
- Hard-coded credentials or URLs.
- Architecture decisions not in `docs/`.
