# shared/ — Shared Library

A Python package imported by every service. Provides cross-cutting concerns that should never be duplicated.

## Modules

| Module | Purpose |
|---|---|
| `auth/` | JWT decode, FastAPI auth dependencies, RBAC decorator |
| `chunking/` | Medical chunker, section detector, token counter |
| `concurrent/` | `gather_with_limit`, `batch_processor`, retry decorator |
| `embedding/` | MiniLM + PubMedBERT clients, dual embedder, cosine similarity |
| `error_handler/` | Base exceptions, FastAPI global handler, `APIResponse` envelope |
| `llm_client/` | LiteLLM wrapper, KV cache, prefix cache, retry, circuit breaker |
| `logger/` | structlog config, request logging middleware |
| `models/` | SQLAlchemy base, pagination schemas, common Pydantic types |
| `progress/` | Redis pub/sub publisher, standard event types |
| `rate_limiter/` | slowapi setup, LLM semaphore limiter |
| `security/` | File validator, filename sanitizer, input sanitizer |
| `storage/` | Unified GCS / Azure Blob / S3 adapter |

## Rules

1. **No service depends on another shared module's internal details.** Shared modules expose stable public APIs; their internals can change without breaking services.
2. **No circular imports.** Shared modules can depend on each other, but the dependency graph must be a DAG. If you find yourself needing `shared/A` to import `shared/B` which imports `shared/A`, extract the common type to a third place.
3. **No service-specific logic.** If a function only makes sense in one service, it doesn't belong here. Put it in that service's `utils/`.
4. **Strict typing.** All public functions have full type hints. `mypy --strict` must pass.
5. **Test the public API.** Internal helpers can be tested transitively. The public surface area gets dedicated tests.

## Import Convention

Services import from shared modules using the package-relative form:

```python
from shared.error_handler import APIResponse, MaisysException
from shared.logger import get_logger
from shared.llm_client import LLMClient
from shared.storage import StorageClient
```

Never `import shared` and `shared.error_handler.APIResponse` — always the explicit `from … import`.

## Required Reading

- `docs/technical-guides/part2.md` — full shared library spec
- `docs/technical-guides/part6.md` — design patterns each shared module implements

## When Adding a New Shared Module

This is rare and should be a deliberate decision. Before adding a 13th module, ask:

- Is this genuinely cross-cutting (used by 3+ services)?
- Does it have a clean public API?
- Is there a corresponding doc section in `docs/technical-guides/part2.md`?

If any answer is no, the code probably belongs in a single service, not here.
