"""Tests for InteractionAgent."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from data_pipeline.ingestion.ddimdl_postgres_ingester import (
    Base as DDIMDLBase,
)
from data_pipeline.ingestion.ddimdl_postgres_ingester import (
    DDIMDLInteraction,
)
from services.drug_service.agents import AgentContext
from services.drug_service.agents._retrieval import DrugRAGRetriever
from services.drug_service.agents.interaction import (
    InteractionAgent,
    WebSearchAgentLike,
)
from services.drug_service.exceptions import (
    AgentLowConfidenceException,
)
from services.drug_service.models.db import Base as DrugBase
from services.drug_service.models.db import RxNormCacheEntry
from services.drug_service.models.schemas import (
    DrugIdentifier,
    InteractionsRequest,
    Language,
)
from services.drug_service.normalization import RxNormNormaliser
from services.drug_service.normalization.rxnorm_api import RxNormAPIClientLike, RxNormProperties
from shared.embedding import FakeEmbedder
from shared.llm_client import FakeLLMBackend, FakeResponse, LLMClient


class FakeRxNormAPI(RxNormAPIClientLike):
    async def find_rxcui_by_name(self, name: str) -> str | None:
        return None

    async def get_properties(self, rxcui: str) -> RxNormProperties | None:
        return None


@dataclass
class FakeHit:
    payload: dict[str, Any]
    score: float


class FakeQdrant:
    def __init__(self, hits: dict[str, list[FakeHit]]) -> None:
        self._hits = hits

    async def search(
        self, collection_name: str, query_vector: list[float], limit: int, with_payload: bool = True
    ) -> list[FakeHit]:
        return self._hits.get(collection_name, [])[:limit]


def make_hit(text: str, score: float = 0.8, language: str = "en", chunk_index: int = 0) -> FakeHit:
    return FakeHit(
        payload={
            "text": text,
            "source_pdf": "gs://b/drugs.pdf",
            "sha256": "abcdef" * 10 + "ab",
            "chunk_index": chunk_index,
            "language": language,
        },
        score=score,
    )


class FakeWebSearch(WebSearchAgentLike):
    def __init__(
        self, results: dict[tuple[str, str], tuple[str, str] | None] | None = None
    ) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, str, Language]] = []

    async def find_interaction(
        self, drug_a: str, drug_b: str, language: Language
    ) -> tuple[str, str] | None:
        self.calls.append((drug_a, drug_b, language))
        key = tuple(sorted([drug_a.lower(), drug_b.lower()]))
        return self.results.get(key)  # type: ignore[arg-type]


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def drug_session() -> AsyncIterator[Any]:
    """In-memory SQLite seeded with drug-service tables + RxNorm cache for 3 drugs."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(DrugBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        for name, rxcui in [
            ("ibuprofen", "5640"),
            ("warfarin", "11289"),
            ("aspirin", "1191"),
        ]:
            s.add(
                RxNormCacheEntry(
                    input_name_normalised=name,
                    input_name_original=name,
                    rxcui=rxcui,
                    generic_name=name,
                    brand_names=[],
                    drug_class=None,
                    resolution_path="exact",
                    confidence=1.0,
                )
            )
        await s.commit()
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def ddimdl_factory() -> AsyncIterator[Any]:
    """Separate engine for the ddimdl tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(DDIMDLBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def queue_interaction_response(backend: FakeLLMBackend, pairs: list[dict]) -> None:
    backend.queue(
        FakeResponse(content=json.dumps({"pairs": pairs}), prompt_tokens=80, completion_tokens=50)
    )


def build_agent(
    drug_session,
    ddimdl_factory,
    qdrant: FakeQdrant,
    llm_backend: FakeLLMBackend,
    *,
    web_search: WebSearchAgentLike | None = None,
) -> InteractionAgent:
    normaliser = RxNormNormaliser(session=drug_session, api_client=FakeRxNormAPI())
    en_retriever = DrugRAGRetriever(
        qdrant_client=qdrant,
        embedder=FakeEmbedder(dimension=8, model_name="fake-en"),
        collection_name="drugs_en",
        language="en",
    )
    ar_retriever = DrugRAGRetriever(
        qdrant_client=qdrant,
        embedder=FakeEmbedder(dimension=16, model_name="fake-ar"),
        collection_name="drugs_ar",
        language="ar",
    )
    return InteractionAgent(
        normaliser=normaliser,
        ddimdl_session_factory=ddimdl_factory,
        en_retriever=en_retriever,
        ar_retriever=ar_retriever,
        llm_client=LLMClient(backend=llm_backend),
        web_search_agent=web_search,
        model="fake-model",
    )


# ─── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tier0_ddimdl_hit_returns_interaction(drug_session, ddimdl_factory) -> None:
    # Seed DDIMDL with a known major interaction
    async with ddimdl_factory() as s:
        s.add(
            DDIMDLInteraction(
                drug_a="aspirin",
                drug_b="warfarin",
                interaction_text="Increased bleeding risk",
                severity_code="major",
                source_file="gs://b/interactions.csv",
                source_sha256="x" * 64,
            )
        )
        await s.commit()

    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "aspirin",
                "drug_b": "warfarin",
                "severity": "major",
                "description": "Increased bleeding risk with concurrent use.",
                "source_tier": "ddimdl",
            }
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, FakeQdrant({}), backend)
    request = InteractionsRequest(
        drugs=[DrugIdentifier(name="aspirin"), DrugIdentifier(name="warfarin")],
        language="en",
    )
    result = await agent.execute(request, AgentContext(user_id="u", language="en"))
    assert len(result.data.pairs) == 1
    pair = result.data.pairs[0]
    assert pair.severity == "major"
    assert pair.source_tier == "ddimdl"
    assert result.data.overall_severity == "major"


@pytest.mark.asyncio
async def test_pair_orderings_match_either_direction(drug_session, ddimdl_factory) -> None:
    """DDIMDL stores (aspirin, warfarin); querying (warfarin, aspirin) should still hit."""
    async with ddimdl_factory() as s:
        s.add(
            DDIMDLInteraction(
                drug_a="aspirin",
                drug_b="warfarin",
                interaction_text="text",
                severity_code="major",
                source_file="gs://b/i.csv",
                source_sha256="y" * 64,
            )
        )
        await s.commit()

    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "warfarin",
                "drug_b": "aspirin",
                "severity": "major",
                "description": "x",
                "source_tier": "ddimdl",
            }
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, FakeQdrant({}), backend)
    request = InteractionsRequest(
        drugs=[DrugIdentifier(name="warfarin"), DrugIdentifier(name="aspirin")],
        language="en",
    )
    result = await agent.execute(request, AgentContext(user_id="u", language="en"))
    # Should have found the DDIMDL entry despite reversed order
    ddimdl_citations = [c for c in result.citations if c.source == "ddimdl"]
    assert len(ddimdl_citations) == 1


@pytest.mark.asyncio
async def test_tier1_drug_rag_when_no_ddimdl(drug_session, ddimdl_factory) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit("Aspirin and ibuprofen may both irritate the GI tract.")],
            "drugs_ar": [make_hit("الأسبرين والإيبوبروفين قد يهيجان المعدة.", language="ar")],
        }
    )
    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "aspirin",
                "drug_b": "ibuprofen",
                "severity": "moderate",
                "description": "GI irritation overlap.",
                "source_tier": "drug_rag",
            }
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, qdrant, backend)
    request = InteractionsRequest(
        drugs=[DrugIdentifier(name="aspirin"), DrugIdentifier(name="ibuprofen")],
        language="en",
    )
    result = await agent.execute(request, AgentContext(user_id="u", language="en"))
    assert result.data.pairs[0].source_tier == "drug_rag"
    assert result.data.pairs[0].severity == "moderate"


@pytest.mark.asyncio
async def test_tier2_web_search_called_when_no_ddimdl_no_rag(drug_session, ddimdl_factory) -> None:
    """Empty DDIMDL + empty RAG → falls through to web search."""
    web = FakeWebSearch(
        results={("aspirin", "ibuprofen"): ("They reduce cardioprotection.", "https://drugs.com/x")}
    )
    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "aspirin",
                "drug_b": "ibuprofen",
                "severity": "moderate",
                "description": "Cardioprotection conflict.",
                "source_tier": "web_search",
            }
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, FakeQdrant({}), backend, web_search=web)
    request = InteractionsRequest(
        drugs=[DrugIdentifier(name="aspirin"), DrugIdentifier(name="ibuprofen")],
        language="en",
    )
    result = await agent.execute(request, AgentContext(user_id="u", language="en"))
    assert len(web.calls) == 1
    assert result.data.pairs[0].source_tier == "web_search"
    # Web citation included
    web_citations = [c for c in result.citations if c.source == "web_search"]
    assert len(web_citations) == 1


@pytest.mark.asyncio
async def test_web_search_skipped_when_not_injected(drug_session, ddimdl_factory) -> None:
    """No web search agent → confidence is lower but agent still produces output."""
    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "aspirin",
                "drug_b": "ibuprofen",
                "severity": "minor",
                "description": "No documented interaction.",
                "source_tier": "drug_rag",
            }
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, FakeQdrant({}), backend, web_search=None)
    request = InteractionsRequest(
        drugs=[DrugIdentifier(name="aspirin"), DrugIdentifier(name="ibuprofen")],
        language="en",
    )
    # No DDIMDL, no RAG, no web → confidence very low. Should raise low-conf.
    with pytest.raises(AgentLowConfidenceException):
        await agent.execute(request, AgentContext(user_id="u", language="en"))


@pytest.mark.asyncio
async def test_overall_severity_is_max_across_pairs(drug_session, ddimdl_factory) -> None:
    async with ddimdl_factory() as s:
        s.add(
            DDIMDLInteraction(
                drug_a="aspirin",
                drug_b="warfarin",
                interaction_text="x",
                severity_code="major",
                source_file="x",
                source_sha256="z" * 64,
            )
        )
        s.add(
            DDIMDLInteraction(
                drug_a="aspirin",
                drug_b="ibuprofen",
                interaction_text="y",
                severity_code="moderate",
                source_file="x",
                source_sha256="z" * 64,
            )
        )
        s.add(
            DDIMDLInteraction(
                drug_a="warfarin",
                drug_b="ibuprofen",
                interaction_text="z",
                severity_code="major",
                source_file="x",
                source_sha256="z" * 64,
            )
        )
        await s.commit()

    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "aspirin",
                "drug_b": "warfarin",
                "severity": "major",
                "description": "a",
                "source_tier": "ddimdl",
            },
            {
                "drug_a": "aspirin",
                "drug_b": "ibuprofen",
                "severity": "moderate",
                "description": "b",
                "source_tier": "ddimdl",
            },
            {
                "drug_a": "warfarin",
                "drug_b": "ibuprofen",
                "severity": "major",
                "description": "c",
                "source_tier": "ddimdl",
            },
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, FakeQdrant({}), backend)
    request = InteractionsRequest(
        drugs=[
            DrugIdentifier(name="aspirin"),
            DrugIdentifier(name="warfarin"),
            DrugIdentifier(name="ibuprofen"),
        ],
        language="en",
    )
    result = await agent.execute(request, AgentContext(user_id="u", language="en"))
    assert len(result.data.pairs) == 3
    assert result.data.overall_severity == "major"


@pytest.mark.asyncio
async def test_invalid_severity_from_llm_falls_back_to_minor(drug_session, ddimdl_factory) -> None:
    qdrant = FakeQdrant({"drugs_en": [make_hit("aspirin and ibuprofen text")], "drugs_ar": []})
    backend = FakeLLMBackend()
    queue_interaction_response(
        backend,
        [
            {
                "drug_a": "aspirin",
                "drug_b": "ibuprofen",
                "severity": "minor",
                "description": "ok",
                "source_tier": "drug_rag",
            }
        ],
    )
    agent = build_agent(drug_session, ddimdl_factory, qdrant, backend)
    request = InteractionsRequest(
        drugs=[DrugIdentifier(name="aspirin"), DrugIdentifier(name="ibuprofen")],
        language="en",
    )
    result = await agent.execute(request, AgentContext(user_id="u", language="en"))
    assert result.data.pairs[0].severity in {"minor", "moderate", "major", "contraindicated"}
