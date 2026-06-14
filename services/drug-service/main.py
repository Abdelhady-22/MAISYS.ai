"""drug-service entry point.

Build the FastAPI app with ``create_app()`` from tests so each test
gets a fresh instance; ``app`` is the module-level singleton for
uvicorn.

Wired here (in order):

1. Structured logging via ``shared.logger.configure_logging``.
2. Database engine via ``shared.models.setup_db``.
3. Request-scoped logging middleware (adds ``request_id`` to every log).
4. Global exception handlers via
   ``shared.error_handler.setup_exception_handlers``.
5. CORS — open by default in dev; restrict via ``CORS_ORIGINS`` env.
6. Every router from ``routes.ALL_ROUTERS``.
7. Prometheus instrumentation at ``/metrics`` if available.

Configuration is read from environment variables in
``_load_config()``. Default values are dev-only — production deploys
must override them via the secret store.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.drug_service.routes import ALL_ROUTERS
from shared.error_handler import setup_exception_handlers
from shared.logger import RequestLoggingMiddleware, configure_logging, get_logger
from shared.models import setup_db

_log = get_logger(__name__)


@dataclass(frozen=True)
class DrugServiceConfig:
    app_env: str
    log_level: str
    database_url: str
    cors_origins: list[str]
    enable_metrics: bool
    enable_agent_wiring: bool = True
    """Set False in tests to skip startup wiring (no Qdrant/LLM calls)."""

    @classmethod
    def from_env(cls) -> DrugServiceConfig:
        cors_raw = os.environ.get("CORS_ORIGINS", "*")
        return cls(
            app_env=os.environ.get("APP_ENV", "development"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://maisys:changeme_local_only@postgres:5432/drug",
            ),
            cors_origins=[o.strip() for o in cors_raw.split(",")] if cors_raw != "*" else ["*"],
            enable_metrics=os.environ.get("ENABLE_METRICS", "true").lower() == "true",
            enable_agent_wiring=os.environ.get("ENABLE_AGENT_WIRING", "true").lower() == "true",
        )


def create_app(config: DrugServiceConfig | None = None) -> FastAPI:
    """Construct a fully-wired FastAPI app.

    Tests call this directly with a custom config. Production uses
    the module-level ``app`` built from environment variables.
    """
    cfg = config or DrugServiceConfig.from_env()
    configure_logging(env=cfg.app_env, log_level=cfg.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _log.info("drug_service.startup", app_env=cfg.app_env)
        setup_db(cfg.database_url)
        if cfg.enable_agent_wiring:
            from services.drug_service.wiring import (
                WiringConfig,
                wire_agents_and_orchestrator,
            )

            try:
                await wire_agents_and_orchestrator(_app, WiringConfig.from_env())
            except Exception as exc:
                _log.exception("drug_service.wiring_failed_continuing_degraded", error=str(exc))
        yield
        _log.info("drug_service.shutdown")

    fastapi_app = FastAPI(
        title="MAISYS drug-service",
        description="Drug lookup, interactions, dosage, pharmacokinetics, and comparison — bilingual ar/en.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Order matters: CORS before request-logging so the request_id
    # is set after CORS preflight is handled.
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    fastapi_app.add_middleware(RequestLoggingMiddleware)

    setup_exception_handlers(fastapi_app)

    for router in ALL_ROUTERS:
        fastapi_app.include_router(router)

    if cfg.enable_metrics:
        _try_enable_metrics(fastapi_app)

    return fastapi_app


def _try_enable_metrics(app: FastAPI) -> None:
    """Mount Prometheus instrumentation if the package is available."""
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:
        _log.info(
            "drug_service.metrics.disabled",
            reason="prometheus_fastapi_instrumentator not installed",
        )
        return
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    _log.info("drug_service.metrics.enabled", endpoint="/metrics")


# Module-level app for uvicorn
app = create_app()


__all__ = ["DrugServiceConfig", "app", "create_app"]
