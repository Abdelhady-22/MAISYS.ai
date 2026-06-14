"""auth-service entry point.

Wires the FastAPI app with:

* **Lifespan** — initialises structured logging and the DB engine on
  startup. The DB pool is owned by ``shared.models`` and cleans up
  automatically when the process exits.
* **Rate limiting** — slowapi with a global ``default_limits`` rule
  applied via ``SlowAPIMiddleware``. Individual routes can be tuned
  later by adding ``@limiter.limit("X/period")`` decorators without
  touching this file.
* **CORS** — origins controlled by ``CORS_ORIGINS`` env var (comma-
  separated; ``"*"`` for any origin).
* **Request logging** — ``RequestLoggingMiddleware`` attaches a
  correlation ID and emits structured request/response logs with the
  sensitive-field scrubber engaged.
* **Exception handling** — typed ``MaisysException`` subclasses are
  translated to ``APIResponse`` envelopes by
  ``setup_exception_handlers``.
* **Prometheus** — ``prometheus-fastapi-instrumentator`` exposes
  ``/metrics`` for scraping.
* **Routes** — every router in ``routes.ALL_ROUTERS`` mounted at root.
* **Health endpoints** — ``/health`` and ``/ready`` for k8s probes.

Run locally::

    PYTHONPATH=. DATABASE_URL=sqlite+aiosqlite:///./dev.db \\
        JWT_SECRET=devsecret python main.py

Or in production::

    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from routes import ALL_ROUTERS
from shared.error_handler import setup_exception_handlers
from shared.logger import RequestLoggingMiddleware, configure_logging
from shared.models import setup_db


def _cors_origins() -> list[str]:
    """Parse CORS_ORIGINS env into a list. ``'*'`` means any origin."""
    raw = os.environ.get("CORS_ORIGINS", "*")
    if raw.strip() == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise logging + DB engine on startup."""
    configure_logging(
        env=os.environ.get("APP_ENV", "production"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required (e.g. " "'postgresql+asyncpg://user:pass@host:5432/dbname')"
        )
    setup_db(database_url)
    yield
    # Engine cleanup is handled by shared.models on process exit.


# Global rate limiter. ``default_limits`` are enforced on every endpoint
# via ``SlowAPIMiddleware``; per-route refinement is a future enhancement.
# Tests set ``RATE_LIMIT_ENABLED=false`` (and typically don't include
# ``SlowAPIMiddleware`` at all — see ``tests/routes/conftest.py``).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[os.environ.get("RATE_LIMIT_DEFAULT", "100/minute")],
    enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true",
)


def create_app() -> FastAPI:
    """Application factory.

    Exposed as a factory so the integration test suite (Stage 13) can
    construct fresh app instances against ephemeral databases without
    touching the module-level ``app`` singleton.
    """
    app = FastAPI(
        title="auth-service",
        description="MAISYS authentication and authorisation service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Rate limiting — must be wired before the middleware that uses it.
    app.state.limiter = limiter
    # slowapi's handler is typed more narrowly than Starlette expects; the
    # mismatch is purely a type-system artefact (slowapi handles only its
    # own RateLimitExceeded exception, which is fine for our purposes).
    app.add_exception_handler(
        RateLimitExceeded, _rate_limit_exceeded_handler  # type: ignore[arg-type]
    )
    app.add_middleware(SlowAPIMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Structured request logging with correlation IDs.
    app.add_middleware(RequestLoggingMiddleware)

    # Typed exception → APIResponse envelope translators.
    setup_exception_handlers(app)

    # Prometheus instrumentation (exposes /metrics).
    Instrumentator().instrument(app).expose(app, include_in_schema=False)

    # Mount every auth route.
    for router in ALL_ROUTERS:
        app.include_router(router)

    # Kubernetes liveness / readiness probes.
    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    async def ready() -> dict[str, str]:
        # Could ping the DB here if we want a stricter ready signal.
        return {"status": "ready"}

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("APP_ENV", "production") == "development",
    )
