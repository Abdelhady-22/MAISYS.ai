"""FastAPI app factory for notification-service.

Per Part 1 §7.10 the service owns ``maisys_notification_db``. The
lifespan wires up:

* SQLAlchemy async engine + session_factory → ``app.state``
* SendGrid email adapter (production) or env-controlled fake
* NotificationSender (orchestrator) bound to both
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.notification_service.routes import ALL_ROUTERS
from services.notification_service.services.email_adapter import SendGridAdapter
from services.notification_service.services.notification_sender import (
    NotificationSender,
)
from shared.error_handler import setup_exception_handlers
from shared.logger import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class NotificationServiceConfig:
    app_env: str
    log_level: str
    database_url: str
    cors_origins: list[str]
    enable_metrics: bool
    enable_wiring: bool = True
    """Set False in tests to skip lifespan wiring."""

    @classmethod
    def from_env(cls) -> NotificationServiceConfig:
        cors_raw = os.environ.get("CORS_ORIGINS", "*")
        return cls(
            app_env=os.environ.get("APP_ENV", "development"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://maisys:changeme_local_only@postgres:5432/maisys_notification_db",
            ),
            cors_origins=([o.strip() for o in cors_raw.split(",")] if cors_raw != "*" else ["*"]),
            enable_metrics=os.environ.get("ENABLE_METRICS", "true").lower() == "true",
            enable_wiring=os.environ.get("ENABLE_WIRING", "true").lower() == "true",
        )


def create_app(config: NotificationServiceConfig | None = None) -> FastAPI:
    cfg = config or NotificationServiceConfig.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _log.info("notification_service.startup", app_env=cfg.app_env)
        if cfg.enable_wiring:
            try:
                _wire(_app, cfg)
            except Exception as exc:
                _log.exception(
                    "notification_service.wiring_failed_continuing_degraded",
                    error=str(exc),
                )
        yield
        _log.info("notification_service.shutdown")

    app = FastAPI(
        title="MAISYS notification-service",
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
            _log.info("notification_service.metrics.enabled", endpoint="/metrics")
        except ImportError:
            _log.warning("notification_service.metrics.disabled")

    return app


def _wire(app: FastAPI, cfg: NotificationServiceConfig) -> None:
    """Build DB engine + email adapter + sender and bind to app.state."""
    engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    email_adapter = SendGridAdapter()
    app.state.email_adapter = email_adapter

    app.state.notification_sender = NotificationSender(
        email_adapter=email_adapter,
        session_factory=session_factory,
    )
    _log.info("notification_service.wired", db=cfg.database_url.split("@")[-1])


app = create_app()


__all__ = ["NotificationServiceConfig", "app", "create_app"]
