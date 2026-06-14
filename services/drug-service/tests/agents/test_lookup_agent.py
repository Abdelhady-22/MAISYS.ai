"""Tests for LookupAgent.

Uses:
- In-memory SQLite for the RxNorm cache.
- FakeRxNormAPI for upstream normalisation.
- FakeQdrant returning scripted chunks.
- FakeLLMBackend returning scripted JSON responses.
- FakeEmbedder for the retrievers.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.drug_service.agents import AgentContext, LookupAgent
from services.drug_service.agents._retrieval import DrugRAGRetriever
from services.drug_service.exceptions import (
    AgentExecutionFailure,
    AgentLowConfidenceException,
    DrugNotFoundException,
)
from services.drug_service.models.db import Base, RxNormCacheEntry
from services.drug_service.models.schemas import DrugIdentifier, LookupRequest
from services.drug_service.normalization import RxNormNormaliser
from services.drug_service.normalization.rxnorm_api import RxNormAPIClientLike, RxNormProperties
from shared.embedding import FakeEmbedder
from shared.llm_client import (
    FakeLLMBackend,
    FakeResponse,
    LLMClient,
)

# ─── Fakes ────────────────────────────────────────────────────────


class FakeRxNormAPI(RxNormAPIClientLike):
    def __init__(self) -> None:
        self.names_to_rxcui: dict[str, str | None] = {}
        self.rxcui_to_props: dict[str, RxNormProperties] = {}

    async def find_rxcui_by_name(self, name: str) -> str | None:
        return self.names_to_rxcui.get(name.lower())

    async def get_properties(self, rxcui: str) -> RxNormProperties | None:
        return self.rxcui_to_props.get(rxcui)


@dataclass
class FakeQdrantHit:
    payload: dict[str, Any]
    score: float


class FakeQdrant:
    """Returns scripted hits per (collection, query) — keyed by collection only."""

    def __init__(self, hits_by_collection: dict[str, list[FakeQdrantHit]]) -> None:
        self.hits_by_collection = hits_by_collection
        self.calls: list[tuple[str, list[float], int]] = []

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        with_payload: bool = True,
    ) -> list[FakeQdrantHit]:
        self.calls.append((collection_name, query_vector, limit))
        return self.hits_by_collection.get(collection_name, [])[:limit]


def make_hit(
    *, text: str, score: float, source_pdf: str, chunk_index: int = 0, language: str = "en"
) -> FakeQdrantHit:
    return FakeQdrantHit(
        payload={
            "text": text,
            "source_pdf": source_pdf,
            "sha256": "deadbeef" * 8,
            "chunk_index": chunk_index,
            "language": language,
        },
        score=score,
    )


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # Seed an ibuprofen cache entry so resolve() can succeed in tier 1.
        s.add(
            RxNormCacheEntry(
                input_name_normalised="ibuprofen",
                input_name_original="ibuprofen",
                rxcui="5640",
                generic_name="ibuprofen",
                brand_names=["Advil", "Motrin"],
                drug_class="NSAID",
                resolution_path="exact",
                confidence=1.0,
            )
        )
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
def llm_backend() -> FakeLLMBackend:
    return FakeLLMBackend()


@pytest.fixture
def llm_client(llm_backend: FakeLLMBackend) -> LLMClient:
    return LLMClient(backend=llm_backend)


def build_agent(
    session: AsyncSession,
    qdrant: FakeQdrant,
    llm_client: LLMClient,
) -> LookupAgent:
    normaliser = RxNormNormaliser(session=session, api_client=FakeRxNormAPI())
    en_embedder = FakeEmbedder(dimension=8, model_name="fake-en")
    ar_embedder = FakeEmbedder(dimension=16, model_name="fake-ar")
    en_retriever = DrugRAGRetriever(
        qdrant_client=qdrant,
        embedder=en_embedder,
        collection_name="drugs_en",
        language="en",
    )
    ar_retriever = DrugRAGRetriever(
        qdrant_client=qdrant,
        embedder=ar_embedder,
        collection_name="drugs_ar",
        language="ar",
    )
    return LookupAgent(
        normaliser=normaliser,
        en_retriever=en_retriever,
        ar_retriever=ar_retriever,
        llm_client=llm_client,
        model="fake-model",
        top_k=3,
    )


def queue_lookup_responses(backend: FakeLLMBackend, en_payload: dict, ar_payload: dict) -> None:
    """Helper: queue two JSON responses (one for each language)."""
    # NOTE: agent fans out en + ar in parallel via asyncio.gather. The fake
    # backend's queue is FIFO; pytest_asyncio's event loop schedules the en
    # task first, so en comes first. Order is deterministic for tests.
    backend.queue(
        FakeResponse(content=json.dumps(en_payload), prompt_tokens=100, completion_tokens=50)
    )
    backend.queue(
        FakeResponse(content=json.dumps(ar_payload), prompt_tokens=100, completion_tokens=50)
    )


# ─── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_bilingual_lookup_data(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [
                make_hit(
                    text="Ibuprofen is an NSAID used to relieve mild to moderate pain.",
                    score=0.85,
                    source_pdf="gs://b/raw/drugs_com/ibuprofen.pdf",
                )
            ],
            "drugs_ar": [
                make_hit(
                    text="الإيبوبروفين دواء مضاد للالتهاب يستخدم لتخفيف الألم.",
                    score=0.82,
                    source_pdf="gs://b/raw/drugs_com/ibuprofen.pdf",
                    language="ar",
                )
            ],
        }
    )
    queue_lookup_responses(
        llm_backend,
        en_payload={
            "indications": ["mild pain", "fever"],
            "mechanism_of_action": "inhibits cyclooxygenase enzymes",
            "contraindications": ["active peptic ulcer"],
        },
        ar_payload={
            "indications": ["ألم خفيف", "حمى"],
            "mechanism_of_action": "تثبيط إنزيمات الأكسدة الحلقية",
            "contraindications": ["قرحة هضمية نشطة"],
        },
    )

    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en")
    context = AgentContext(user_id="u1", language="en")

    response = await agent.execute(request, context)
    data = response.data
    assert data.rxcui == "5640"
    assert data.generic_name == "ibuprofen"
    assert "Advil" in data.brand_names
    assert data.drug_class == "NSAID"
    # Bilingual indications: 2 pairs, both langs filled
    assert len(data.indications) == 2
    assert data.indications[0].en == "mild pain"
    assert data.indications[0].ar == "ألم خفيف"
    # Mechanism of action present in both languages
    assert data.mechanism_of_action is not None
    assert "cyclooxygenase" in data.mechanism_of_action.en
    assert "الأكسدة" in data.mechanism_of_action.ar
    # Citations from both retrievals (deduped — same chunk in both collections)
    assert len(response.citations) >= 1
    assert any("ibuprofen" in c.title for c in response.citations if c.title)


@pytest.mark.asyncio
async def test_uneven_indication_counts_pad_with_empty(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit(text="en chunk", score=0.8, source_pdf="x.pdf")],
            "drugs_ar": [make_hit(text="ar chunk", score=0.75, source_pdf="x.pdf", language="ar")],
        }
    )
    queue_lookup_responses(
        llm_backend,
        en_payload={
            "indications": ["pain", "fever", "inflammation"],
            "mechanism_of_action": "",
            "contraindications": ["pregnancy"],
        },
        ar_payload={
            "indications": ["ألم"],  # only 1 vs en's 3
            "mechanism_of_action": "",
            "contraindications": ["حمل", "قرحة"],
        },
    )

    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en")
    response = await agent.execute(request, AgentContext(user_id="u", language="en"))
    # Indications: 3 entries (en is longer); ar gets padded with ""
    assert len(response.data.indications) == 3
    assert response.data.indications[0].en == "pain"
    assert response.data.indications[0].ar == "ألم"
    assert response.data.indications[1].ar == ""
    # Contraindications: ar is longer; en gets padded
    assert len(response.data.contraindications) == 2


@pytest.mark.asyncio
async def test_no_chunks_in_either_collection_low_confidence(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant({"drugs_en": [], "drugs_ar": []})
    # No LLM call expected when both retrievals are empty (agent short-circuits)
    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en")
    # confidence drops to 0.3 (below 0.7 threshold) → raises
    with pytest.raises(AgentLowConfidenceException):
        await agent.execute(request, AgentContext(user_id="u", language="en"))


@pytest.mark.asyncio
async def test_one_collection_empty_renders_other_at_moderate_confidence(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    """When one language has chunks and the other doesn't, confidence = 0.6.
    Still below default min_confidence=0.7 → still raises low-confidence.
    """
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit(text="en chunk", score=0.9, source_pdf="x.pdf")],
            "drugs_ar": [],
        }
    )
    queue_lookup_responses(
        llm_backend,
        en_payload={
            "indications": ["pain"],
            "mechanism_of_action": "mech",
            "contraindications": [],
        },
        ar_payload={"indications": [], "mechanism_of_action": "", "contraindications": []},
    )
    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en")
    with pytest.raises(AgentLowConfidenceException):
        await agent.execute(request, AgentContext(user_id="u", language="en"))


@pytest.mark.asyncio
async def test_drug_not_found_at_normalisation(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant({})
    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="not-a-real-drug-xyz"), language="en")
    with pytest.raises(DrugNotFoundException):
        await agent.execute(request, AgentContext(user_id="u", language="en"))


@pytest.mark.asyncio
async def test_identifier_with_neither_name_nor_rxcui_raises(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant({})
    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(), language="en")
    with pytest.raises(DrugNotFoundException):
        await agent.execute(request, AgentContext(user_id="u", language="en"))


@pytest.mark.asyncio
async def test_malformed_llm_response_after_retry_fails(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit(text="en chunk", score=0.8, source_pdf="x.pdf")],
            "drugs_ar": [make_hit(text="ar chunk", score=0.8, source_pdf="x.pdf", language="ar")],
        }
    )
    # First call: garbage. Retry call: still garbage. Second language same.
    for _ in range(4):
        llm_backend.queue(FakeResponse(content="not json at all"))
    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en")
    with pytest.raises(AgentExecutionFailure):
        await agent.execute(request, AgentContext(user_id="u", language="en"))


@pytest.mark.asyncio
async def test_llm_returns_json_in_markdown_fence(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    """The JSON extractor handles ```json fenced output gracefully."""
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit(text="en chunk", score=0.85, source_pdf="x.pdf")],
            "drugs_ar": [make_hit(text="ar chunk", score=0.85, source_pdf="x.pdf", language="ar")],
        }
    )
    en_json = '{"indications": ["pain"], "mechanism_of_action": "mech", "contraindications": []}'
    ar_json = '{"indications": ["ألم"], "mechanism_of_action": "آلية", "contraindications": []}'
    llm_backend.queue(FakeResponse(content=f"Here you go:\n```json\n{en_json}\n```"))
    llm_backend.queue(FakeResponse(content=f"```\n{ar_json}\n```"))

    agent = build_agent(session, qdrant, llm_client)
    request = LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en")
    response = await agent.execute(request, AgentContext(user_id="u", language="en"))
    assert response.data.indications[0].en == "pain"
    assert response.data.indications[0].ar == "ألم"


@pytest.mark.asyncio
async def test_disclaimer_attached(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit(text="en chunk", score=0.85, source_pdf="x.pdf")],
            "drugs_ar": [make_hit(text="ar chunk", score=0.85, source_pdf="x.pdf", language="ar")],
        }
    )
    queue_lookup_responses(
        llm_backend,
        en_payload={"indications": ["pain"], "mechanism_of_action": "m", "contraindications": []},
        ar_payload={"indications": ["ألم"], "mechanism_of_action": "م", "contraindications": []},
    )
    agent = build_agent(session, qdrant, llm_client)
    response = await agent.execute(
        LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en"),
        AgentContext(user_id="u", language="en"),
    )
    # Generic disclaimer is the default for Lookup
    assert response.meta.disclaimer.en
    assert response.meta.disclaimer.ar
    assert "educational" in response.meta.disclaimer.en.lower()


@pytest.mark.asyncio
async def test_searches_both_collections(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit(text="en chunk", score=0.85, source_pdf="x.pdf")],
            "drugs_ar": [make_hit(text="ar chunk", score=0.85, source_pdf="x.pdf", language="ar")],
        }
    )
    queue_lookup_responses(
        llm_backend,
        en_payload={"indications": ["pain"], "mechanism_of_action": "m", "contraindications": []},
        ar_payload={"indications": ["ألم"], "mechanism_of_action": "م", "contraindications": []},
    )
    agent = build_agent(session, qdrant, llm_client)
    await agent.execute(
        LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en"),
        AgentContext(user_id="u", language="en"),
    )
    collections_searched = {call[0] for call in qdrant.calls}
    assert collections_searched == {"drugs_en", "drugs_ar"}


@pytest.mark.asyncio
async def test_citations_deduplicated_across_languages(
    session: AsyncSession, llm_backend: FakeLLMBackend, llm_client: LLMClient
) -> None:
    """If the same source chunk appears in both collections, cite once."""
    same_chunk_en = make_hit(text="t", score=0.8, source_pdf="x.pdf", chunk_index=5)
    same_chunk_ar = make_hit(text="ت", score=0.8, source_pdf="x.pdf", chunk_index=5, language="ar")
    different_chunk = make_hit(text="other", score=0.7, source_pdf="x.pdf", chunk_index=9)
    qdrant = FakeQdrant({"drugs_en": [same_chunk_en, different_chunk], "drugs_ar": [same_chunk_ar]})
    queue_lookup_responses(
        llm_backend,
        en_payload={"indications": ["pain"], "mechanism_of_action": "m", "contraindications": []},
        ar_payload={"indications": ["ألم"], "mechanism_of_action": "م", "contraindications": []},
    )
    agent = build_agent(session, qdrant, llm_client)
    response = await agent.execute(
        LookupRequest(drug=DrugIdentifier(name="ibuprofen"), language="en"),
        AgentContext(user_id="u", language="en"),
    )
    # 3 input hits, but chunk_index=5 appears twice → 2 unique citations
    assert len(response.citations) == 2
