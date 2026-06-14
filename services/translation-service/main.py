"""FastAPI app factory for translation-service.

Per Part 1 §7.7 the service is stateless with a Redis cache. The
lifespan wires:

* Cache — Redis when ``REDIS_URL`` is set, in-memory otherwise
* Translators — Google (if API key present), Local (if SDK present),
  LLM (if API key for the chosen provider present)
* TranslationService — orchestrator

Modes that aren't configured at startup raise
``TranslationModeUnavailable`` on first use; ``/readyz`` reports
which modes are available so operators can spot misconfigured
deploys immediately.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.translation_service.repository.cache_repo import (
    InMemoryTranslationCache,
    RedisTranslationCache,
    TranslationCache,
)
from services.translation_service.routes import ALL_ROUTERS
from services.translation_service.services.mode_selector import ModeSelector
from services.translation_service.services.translation_service import (
    TranslationService,
)
from services.translation_service.services.translators.google_translator import (
    GoogleTranslator,
)
from services.translation_service.services.translators.llm_translator import (
    LLMTranslator,
)
from services.translation_service.services.translators.local_translator import (
    LocalTranslator,
)
from services.translation_service.services.translators.protocol import Translator
from shared.error_handler import setup_exception_handlers
from shared.logger import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class TranslationServiceConfig:
    app_env: str
    log_level: str
    redis_url: str | None
    cors_origins: list[str]
    enable_metrics: bool
    enable_wiring: bool = True

    @classmethod
    def from_env(cls) -> TranslationServiceConfig:
        cors_raw = os.environ.get("CORS_ORIGINS", "*")
        return cls(
            app_env=os.environ.get("APP_ENV", "development"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            redis_url=os.environ.get("REDIS_URL") or None,
            cors_origins=([o.strip() for o in cors_raw.split(",")] if cors_raw != "*" else ["*"]),
            enable_metrics=os.environ.get("ENABLE_METRICS", "true").lower() == "true",
            enable_wiring=os.environ.get("ENABLE_WIRING", "true").lower() == "true",
        )


def create_app(config: TranslationServiceConfig | None = None) -> FastAPI:
    cfg = config or TranslationServiceConfig.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _log.info("translation_service.startup", app_env=cfg.app_env)
        if cfg.enable_wiring:
            try:
                _wire(_app, cfg)
            except Exception as exc:
                _log.exception(
                    "translation_service.wiring_failed_continuing_degraded",
                    error=str(exc),
                )
        yield
        _log.info("translation_service.shutdown")

    app = FastAPI(
        title="MAISYS translation-service",
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
            _log.info("translation_service.metrics.enabled", endpoint="/metrics")
        except ImportError:
            _log.warning("translation_service.metrics.disabled")

    return app


def _wire(app: FastAPI, cfg: TranslationServiceConfig) -> None:
    """Construct cache + translators + selector + service."""
    cache: TranslationCache
    if cfg.redis_url:
        cache = RedisTranslationCache(redis_url=cfg.redis_url)
        _log.info("translation_service.cache.redis", url=cfg.redis_url)
    else:
        cache = InMemoryTranslationCache()
        _log.warning(
            "translation_service.cache.in_memory",
            reason="REDIS_URL not set — production should configure Redis",
        )
    app.state.cache = cache

    google: Translator | None = None
    if os.environ.get("GOOGLE_TRANSLATE_API_KEY"):
        google = GoogleTranslator()

    local: Translator | None = None
    try:
        import deep_translator  # noqa: F401

        local = LocalTranslator()
    except ImportError:
        _log.info("translation_service.local_translator.unavailable")

    llm: Translator | None = None
    try:
        from shared.llm_client import LLMClient

        llm_client = LLMClient.from_env()
        llm = LLMTranslator(llm_client=llm_client)
    except Exception as exc:
        _log.warning("translation_service.llm_translator.unavailable", error=str(exc))

    selector = ModeSelector(google=google, local=local, llm=llm)
    app.state.mode_selector = selector
    _log.info(
        "translation_service.modes_wired",
        modes=selector.available_modes(),
    )

    app.state.translation_service = TranslationService(mode_selector=selector, cache=cache)


app = create_app()


__all__ = ["TranslationServiceConfig", "app", "create_app"]
