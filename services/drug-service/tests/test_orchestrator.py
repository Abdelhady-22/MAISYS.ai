"""Tests for DrugQueryOrchestrator."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.drug_service.agents import (
    AgentRegistry,
    LookupAgent,
)
from services.drug_service.agents._retrieval import DrugRAGRetriever
from services.drug_service.exceptions import OrchestratorRoutingFailure
from services.drug_service.models.db import Base, RxNormCacheEntry
from services.drug_service.models.schemas import QueryRequest
from services.drug_service.normalization import RxNormNormaliser
from services.drug_service.normalization.rxnorm_api import RxNormAPIClientLike, RxNormProperties
from services.drug_service.orchestrator import DrugQueryOrchestrator
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
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        with_payload: bool = True,
    ) -> list[FakeHit]:
        return self._hits.get(collection_name, [])[:limit]


def make_hit(text: str, score: float = 0.85, chunk_index: int = 0) -> FakeHit:
    return FakeHit(
        payload={
            "text": text,
            "source_pdf": "x.pdf",
            "sha256": "abc" * 21 + "a",
            "chunk_index": chunk_index,
            "language": "en",
        },
        score=score,
    )


@pytest_asyncio.fixture
async def session() -> AsyncIterator[Any]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            RxNormCacheEntry(
                input_name_normalised="ibuprofen",
                input_name_original="ibuprofen",
                rxcui="5640",
                generic_name="ibuprofen",
                brand_names=["Advil"],
                drug_class="NSAID",
                resolution_path="exact",
                confidence=1.0,
            )
        )
        await s.commit()
        yield s
    await engine.dispose()


def build_orchestrator_with_lookup(session) -> tuple[DrugQueryOrchestrator, FakeLLMBackend]:
    """Build an orchestrator with only the Lookup agent registered."""
    backend = FakeLLMBackend()
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit("Ibuprofen is an NSAID for pain.")],
            "drugs_ar": [make_hit("الإيبوبروفين دواء.")],
        }
    )
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
    llm = LLMClient(backend=backend)
    lookup = LookupAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_retriever,
        ar_retriever=ar_retriever,
        llm_client=llm,
        model="fake",
    )
    registry = AgentRegistry()
    registry.register(lookup)
    orchestrator = DrugQueryOrchestrator(registry=registry, llm_client=llm, model="fake")
    return orchestrator, backend


@pytest.mark.asyncio
async def test_routes_lookup_query_to_lookup_agent(session, monkeypatch) -> None:
    """Free-text 'what is ibuprofen' classified → lookup → LookupAgent runs."""
    # Disable safety check
    monkeypatch.setenv("SAFETY_SERVICE_ENABLED", "false")

    orchestrator, backend = build_orchestrator_with_lookup(session)

    # First LLM call: intent classification
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "intent": "lookup",
                    "drug_names": ["ibuprofen"],
                    "reason": "",
                    "country_iso": None,
                    "patient_age_years": None,
                }
            ),
            prompt_tokens=50,
            completion_tokens=30,
        )
    )
    # Next: LookupAgent's en + ar synth calls
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "indications": ["pain"],
                    "mechanism_of_action": "inhibits COX",
                    "contraindications": [],
                }
            ),
            prompt_tokens=80,
            completion_tokens=40,
        )
    )
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "indications": ["ألم"],
                    "mechanism_of_action": "تثبيط COX",
                    "contraindications": [],
                }
            ),
            prompt_tokens=80,
            completion_tokens=40,
        )
    )

    response = await orchestrator.run(
        QueryRequest(text="what is ibuprofen", language="en"),
        user_id="u1",
    )
    assert response.primary_agent == "lookup"
    assert response.called_agents == ["lookup"]
    assert response.data["rxcui"] == "5640"
    assert response.data["generic_name"] == "ibuprofen"


@pytest.mark.asyncio
async def test_unknown_intent_raises_routing_failure(session, monkeypatch) -> None:
    monkeypatch.setenv("SAFETY_SERVICE_ENABLED", "false")
    orchestrator, backend = build_orchestrator_with_lookup(session)
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "intent": "unknown",
                    "drug_names": [],
                    "reason": "",
                    "country_iso": None,
                    "patient_age_years": None,
                }
            ),
            prompt_tokens=50,
            completion_tokens=10,
        )
    )
    with pytest.raises(OrchestratorRoutingFailure):
        await orchestrator.run(QueryRequest(text="hello", language="en"), user_id="u1")


@pytest.mark.asyncio
async def test_no_drugs_in_query_raises_routing_failure(session, monkeypatch) -> None:
    monkeypatch.setenv("SAFETY_SERVICE_ENABLED", "false")
    orchestrator, backend = build_orchestrator_with_lookup(session)
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "intent": "lookup",
                    "drug_names": [],
                    "reason": "",
                    "country_iso": None,
                    "patient_age_years": None,
                }
            ),
            prompt_tokens=50,
            completion_tokens=10,
        )
    )
    with pytest.raises(OrchestratorRoutingFailure):
        await orchestrator.run(QueryRequest(text="tell me about it", language="en"), user_id="u1")


@pytest.mark.asyncio
async def test_intent_dispatched_to_unregistered_agent_raises(session, monkeypatch) -> None:
    """If the LLM classifies an intent for an agent that isn't registered, raise."""
    monkeypatch.setenv("SAFETY_SERVICE_ENABLED", "false")
    orchestrator, backend = build_orchestrator_with_lookup(session)
    # Classifier says "dosage" but only "lookup" is registered
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "intent": "dosage",
                    "drug_names": ["ibuprofen"],
                    "reason": "",
                    "country_iso": None,
                    "patient_age_years": None,
                }
            ),
            prompt_tokens=50,
            completion_tokens=10,
        )
    )
    with pytest.raises(OrchestratorRoutingFailure):
        await orchestrator.run(
            QueryRequest(text="how much ibuprofen?", language="en"), user_id="u1"
        )


# ─── PR3: visual_type + job_id ─────────────────────────────────────


@pytest.mark.asyncio
async def test_visual_type_set_by_intent(session, monkeypatch) -> None:
    """Each intent maps to a known visual_type for frontend rendering."""
    monkeypatch.setenv("SAFETY_SERVICE_ENABLED", "false")
    orchestrator, backend = build_orchestrator_with_lookup(session)
    # Classifier → lookup
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "intent": "lookup",
                    "drug_names": ["ibuprofen"],
                    "reason": "",
                    "country_iso": None,
                    "patient_age_years": None,
                }
            ),
            prompt_tokens=50,
            completion_tokens=10,
        )
    )
    # Lookup synth en + ar
    for _ in range(2):
        backend.queue(
            FakeResponse(
                content=json.dumps(
                    {"indications": ["pain"], "mechanism_of_action": "x", "contraindications": []}
                ),
                prompt_tokens=80,
                completion_tokens=40,
            )
        )
    response = await orchestrator.run(
        QueryRequest(text="what is ibuprofen", language="en"), user_id="u"
    )
    # Lookup intent → "card" visual
    assert response.visual_type == "card"


@pytest.mark.asyncio
async def test_job_id_from_request_threaded_to_publisher(session, monkeypatch) -> None:
    """QueryRequest.job_id (PR3) is used as the ProgressPublisher channel id."""
    monkeypatch.setenv("SAFETY_SERVICE_ENABLED", "false")
    orchestrator, backend = build_orchestrator_with_lookup(session)
    backend.queue(
        FakeResponse(
            content=json.dumps(
                {
                    "intent": "lookup",
                    "drug_names": ["ibuprofen"],
                    "reason": "",
                    "country_iso": None,
                    "patient_age_years": None,
                }
            ),
            prompt_tokens=50,
            completion_tokens=10,
        )
    )
    for _ in range(2):
        backend.queue(
            FakeResponse(
                content=json.dumps(
                    {"indications": ["pain"], "mechanism_of_action": "x", "contraindications": []}
                ),
                prompt_tokens=80,
                completion_tokens=40,
            )
        )
    # Capture events through a fake publisher
    published_job_ids: list[str] = []

    class FakePublisher:
        async def publish(self, event):
            published_job_ids.append(event.job_id)
            return 0

    response = await orchestrator.run(
        QueryRequest(text="what is ibuprofen", language="en", job_id="custom-job-id"),
        user_id="u",
        progress_publisher=FakePublisher(),  # type: ignore[arg-type]
    )
    # Every published event used "custom-job-id" as the channel
    assert all(jid == "custom-job-id" for jid in published_job_ids)
    assert response.primary_agent == "lookup"
