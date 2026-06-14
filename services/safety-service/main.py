"""FastAPI app factory for safety-service.

The service is stateless — no database, no Alembic, no repository
layer. The lifespan only wires the in-memory ``EmergencyDetector``
and ``DisclaimerInjector`` onto ``app.state``. Stage 2 LLM is
opt-in via ``SAFETY_LLM_CONFIRM_ENABLED=true``; when disabled the
detector still constructs successfully and ignores any provided
LLM client.

Per the Phase 3 brief safety-service runs on port 8008.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.safety_service.routes import ALL_ROUTERS
from services.safety_service.services.disclaimer_injector import DisclaimerInjector
from services.safety_service.services.emergency_detector import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    DEFAULT_STAGE_2_MODEL,
    EmergencyDetector,
)
from shared.error_handler import setup_exception_handlers
from shared.logger import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class SafetyServiceConfig:
    """Service-level configuration."""

    app_env: str
    log_level: str
    cors_origins: list[str]
    enable_metrics: bool
    stage_2_llm_enabled: bool
    stage_2_llm_model: str
    stage_2_llm_timeout_seconds: float

    @classmethod
    def from_env(cls) -> SafetyServiceConfig:
        cors_raw = os.environ.get("CORS_ORIGINS", "*")
        return cls(
            app_env=os.environ.get("APP_ENV", "development"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            cors_origins=([o.strip() for o in cors_raw.split(",")] if cors_raw != "*" else ["*"]),
            enable_metrics=os.environ.get("ENABLE_METRICS", "true").lower() == "true",
            stage_2_llm_enabled=(
                os.environ.get("SAFETY_LLM_CONFIRM_ENABLED", "false").lower() == "true"
            ),
            stage_2_llm_model=os.environ.get("SAFETY_STAGE_2_MODEL", DEFAULT_STAGE_2_MODEL),
            stage_2_llm_timeout_seconds=float(
                os.environ.get(
                    "SAFETY_STAGE_2_TIMEOUT_SECONDS",
                    str(DEFAULT_LLM_TIMEOUT_SECONDS),
                )
            ),
        )


def create_app(config: SafetyServiceConfig | None = None) -> FastAPI:
    """Build a fully-wired FastAPI app.

    Accepts an optional ``config`` so tests can construct an app with
    fully-deterministic settings without exporting environment vars.
    """
    cfg = config or SafetyServiceConfig.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _log.info(
            "safety_service.startup",
            app_env=cfg.app_env,
            stage_2_llm_enabled=cfg.stage_2_llm_enabled,
        )
        _wire_in_memory_services(_app, cfg)
        yield
        _log.info("safety_service.shutdown")

    app = FastAPI(
        title="MAISYS safety-service",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    setup_exception_handlers(app)

    for router in ALL_ROUTERS:
        app.include_router(router)

    if cfg.enable_metrics:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator

            Instrumentator().instrument(app).expose(app, endpoint="/metrics")
            _log.info("safety_service.metrics.enabled", endpoint="/metrics")
        except ImportError:
            _log.warning(
                "safety_service.metrics.disabled",
                reason="prometheus_fastapi_instrumentator_not_installed",
            )

    return app


def _wire_in_memory_services(app: FastAPI, cfg: SafetyServiceConfig) -> None:
    """Build and attach the detector + injector onto ``app.state``.

    The Stage 2 LLM client is wired lazily: if Stage 2 is enabled we
    try to construct ``LLMClient.from_env()``; if that fails (no API
    key in the env, no Redis for cache, etc.) we log and continue
    with Stage 2 disabled. The service stays usable in degraded mode.
    """
    llm_client = None
    if cfg.stage_2_llm_enabled:
        try:
            from shared.llm_client import LLMClient

            llm_client = LLMClient.from_env()
            _log.info(
                "safety_service.stage_2_llm.wired",
                model=cfg.stage_2_llm_model,
            )
        except Exception as exc:
            _log.warning(
                "safety_service.stage_2_llm.unavailable",
                error=str(exc),
                fallback="stage_2_disabled",
            )

    app.state.emergency_detector = EmergencyDetector(
        llm_client=llm_client,
        stage_2_enabled=cfg.stage_2_llm_enabled and llm_client is not None,
        stage_2_model=cfg.stage_2_llm_model,
        stage_2_timeout_seconds=cfg.stage_2_llm_timeout_seconds,
    )
    app.state.disclaimer_injector = DisclaimerInjector()


# Module-level app for `uvicorn services.safety_service.main:app`
app = create_app()


__all__ = ["SafetyServiceConfig", "app", "create_app"]
