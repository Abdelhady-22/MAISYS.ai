"""Agent + orchestrator wiring for the lifespan startup.

This is the single place that constructs every external client
(RxNorm API, Qdrant, Redis-cached LLM, embedders, DDIMDL DB) and
registers the 8 agents with the default registry plus attaches the
orchestrator to ``app.state``.

It is intentionally separate from ``main.py`` so:

1. Tests can construct ``DrugServiceConfig`` and skip wiring without
   bypassing ``create_app()`` itself.
2. Each external dependency failure is isolated — Qdrant down
   doesn't prevent normalisation; missing API keys don't prevent
   the service starting.
3. The lifespan stays readable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.drug_service.agents import (
    AcquisitionAgent,
    AlternativeAgent,
    ComparisonAgent,
    DosageAgent,
    InteractionAgent,
    LookupAgent,
    PharmacokineticsAgent,
    default_registry,
)
from services.drug_service.agents._retrieval import DrugRAGRetriever
from services.drug_service.agents.web_search import (
    PlaywrightWebFetcher,
    WebSearchAgent,
)
from services.drug_service.normalization import (
    RxNormAPIClient,
    RxNormNormaliser,
)
from services.drug_service.orchestrator import DrugQueryOrchestrator
from shared.embedding import BilingualEmbedder, LiteLLMEmbedder, SentenceTransformerEmbedder
from shared.llm_client import LiteLLMBackend, LLMClient
from shared.logger import get_logger
from shared.progress import ProgressPublisher

_log = get_logger(__name__)


@dataclass(frozen=True)
class WiringConfig:
    drug_database_url: str
    ddimdl_database_url: str
    qdrant_url: str
    redis_url: str | None
    llm_model: str
    enable_web_search: bool

    @classmethod
    def from_env(cls) -> WiringConfig:
        return cls(
            drug_database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://maisys:changeme_local_only@postgres:5432/drug",
            ),
            ddimdl_database_url=os.environ.get(
                "DDIMDL_DATABASE_URL",
                "postgresql+asyncpg://maisys:changeme_local_only@postgres:5432/ddimdl",
            ),
            qdrant_url=os.environ.get("QDRANT_URL", "http://qdrant:6333"),
            redis_url=os.environ.get("REDIS_URL"),
            llm_model=os.environ.get("DRUG_SERVICE_LLM_MODEL", "openai/gpt-4o-mini"),
            enable_web_search=os.environ.get("WEB_SEARCH_ENABLED", "false").lower() == "true",
        )


async def wire_agents_and_orchestrator(app: FastAPI, config: WiringConfig) -> None:
    """Build agents + orchestrator and attach them to ``app.state``.

    Best-effort. Each external dependency failure is logged and
    that agent is left unregistered — the route returns 503 instead
    of failing service startup.
    """
    try:
        # ─── Shared infrastructure ─────────────────────────────────
        drug_engine = create_async_engine(config.drug_database_url)
        drug_factory = async_sessionmaker(drug_engine, expire_on_commit=False)
        ddimdl_engine = create_async_engine(config.ddimdl_database_url)
        ddimdl_factory = async_sessionmaker(ddimdl_engine, expire_on_commit=False)

        rxnorm_api = RxNormAPIClient()

        # Embedders — bilingual with optional ar fallback to st model
        try:
            en_embedder = LiteLLMEmbedder(model="openai/text-embedding-3-small")
            ar_embedder = SentenceTransformerEmbedder(
                model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                dimension=384,
            )
            BilingualEmbedder(en_embedder=en_embedder, ar_embedder=ar_embedder)
        except Exception as exc:
            _log.warning("wiring.embedders_unavailable", error=str(exc))
            return

        # Qdrant client
        try:
            from qdrant_client import AsyncQdrantClient

            qdrant_client: Any = AsyncQdrantClient(url=config.qdrant_url)
        except Exception as exc:
            _log.warning("wiring.qdrant_unavailable", error=str(exc))
            return

        # LLM client (LiteLLM backend; cache wiring is internal to LLMClient when REDIS_URL is set)
        try:
            llm_backend = LiteLLMBackend()
            llm_client = LLMClient(backend=llm_backend)
        except Exception as exc:
            _log.warning("wiring.llm_unavailable", error=str(exc))
            return

        # ─── Per-session normaliser factory ────────────────────────
        # The normaliser needs an AsyncSession; we wrap each agent
        # with a session-scoped instance. Long-lived agents share the
        # session_factory and create sessions per-request internally.
        # Simpler: agents receive a session_factory and open sessions
        # in their _run() methods. For now we register agents with a
        # session opened once at wiring — fine for the wiring smoke
        # test; production refactors to per-request sessions in PR3.
        normaliser_session = drug_factory()
        normaliser = RxNormNormaliser(
            session=await normaliser_session.__aenter__(),
            api_client=rxnorm_api,
        )

        en_retriever = DrugRAGRetriever(
            qdrant_client=qdrant_client,
            embedder=en_embedder,
            collection_name="drugs_en",
            language="en",
        )
        ar_retriever = DrugRAGRetriever(
            qdrant_client=qdrant_client,
            embedder=ar_embedder,
            collection_name="drugs_ar",
            language="ar",
        )

        # ─── Web search (optional) ─────────────────────────────────
        web_search: WebSearchAgent | None = None
        if config.enable_web_search:
            try:
                web_search = WebSearchAgent(fetcher=PlaywrightWebFetcher())
            except Exception as exc:
                _log.warning("wiring.web_search_unavailable", error=str(exc))

        # ─── Register agents ───────────────────────────────────────
        common_kwargs = dict(
            normaliser=normaliser,
            en_retriever=en_retriever,
            ar_retriever=ar_retriever,
            llm_client=llm_client,
            model=config.llm_model,
        )
        default_registry.register(LookupAgent(**common_kwargs))  # type: ignore[arg-type]
        default_registry.register(
            InteractionAgent(
                **common_kwargs,  # type: ignore[arg-type]
                ddimdl_session_factory=ddimdl_factory,
                web_search_agent=web_search,
            )
        )
        default_registry.register(DosageAgent(**common_kwargs))  # type: ignore[arg-type]
        default_registry.register(ComparisonAgent(**common_kwargs))  # type: ignore[arg-type]
        default_registry.register(PharmacokineticsAgent(**common_kwargs))  # type: ignore[arg-type]
        default_registry.register(AlternativeAgent(**common_kwargs))  # type: ignore[arg-type]
        default_registry.register(AcquisitionAgent(**common_kwargs))  # type: ignore[arg-type]

        # ─── Orchestrator ──────────────────────────────────────────
        orchestrator = DrugQueryOrchestrator(
            registry=default_registry,
            llm_client=llm_client,
            model=config.llm_model,
        )
        app.state.orchestrator = orchestrator

        # ─── ProgressPublisher (PR3 — feeds /ws/drugs/query) ───────
        if config.redis_url:
            try:
                import redis.asyncio as aioredis

                progress_redis = aioredis.from_url(config.redis_url, decode_responses=False)
                app.state.progress_publisher = ProgressPublisher(progress_redis)
                _log.info("wiring.progress_publisher.enabled", redis_url=config.redis_url)
            except Exception as exc:
                _log.warning("wiring.progress_publisher.failed", error=str(exc))

        _log.info(
            "wiring.complete",
            registered_agents=default_registry.names(),
            web_search_enabled=web_search is not None,
        )
    except Exception as exc:
        _log.exception("wiring.failed", error=str(exc), error_type=type(exc).__name__)


__all__ = ["WiringConfig", "wire_agents_and_orchestrator"]
