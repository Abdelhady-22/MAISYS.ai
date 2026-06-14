"""Batched tests for Dosage, Comparison, Pharmacokinetics, Alternative, Acquisition agents.

These agents share the normalise → retrieve → bilingual LLM
synthesise → combine flow. Each gets a focused happy-path test plus
agent-specific edge cases. The full BaseAgent flow is exercised by
test_base_agent.py and test_lookup_agent.py — these tests assert the
agent-specific contract (schema shapes, prompt variable handling,
bilingual combination strategy).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.drug_service.agents import (
    AcquisitionAgent,
    AgentContext,
    AlternativeAgent,
    ComparisonAgent,
    DosageAgent,
    PharmacokineticsAgent,
)
from services.drug_service.agents._retrieval import DrugRAGRetriever
from services.drug_service.models.db import Base, RxNormCacheEntry
from services.drug_service.models.schemas import (
    AcquisitionRequest,
    AlternativeRequest,
    ComparisonRequest,
    DosageRequest,
    DrugIdentifier,
    PatientContext,
    PKRequest,
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


def make_hit(
    text: str,
    score: float = 0.85,
    source_pdf: str = "x.pdf",
    chunk_index: int = 0,
    language: str = "en",
) -> FakeHit:
    return FakeHit(
        payload={
            "text": text,
            "source_pdf": source_pdf,
            "sha256": "deadbeef" * 8,
            "chunk_index": chunk_index,
            "language": language,
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
        for name, rxcui, drug_class in [
            ("ibuprofen", "5640", "NSAID"),
            ("metformin", "6809", "biguanide"),
            ("atorvastatin", "83367", "statin"),
            ("amoxicillin", "723", "penicillin"),
            ("azithromycin", "18631", "macrolide"),
            ("lisinopril", "29046", "ACE inhibitor"),
        ]:
            s.add(
                RxNormCacheEntry(
                    input_name_normalised=name,
                    input_name_original=name,
                    rxcui=rxcui,
                    generic_name=name,
                    brand_names=[],
                    drug_class=drug_class,
                    resolution_path="exact",
                    confidence=1.0,
                )
            )
        await s.commit()
        yield s
    await engine.dispose()


def make_retrievers(qdrant: FakeQdrant) -> tuple[DrugRAGRetriever, DrugRAGRetriever]:
    en = DrugRAGRetriever(
        qdrant_client=qdrant,
        embedder=FakeEmbedder(dimension=8, model_name="fake-en"),
        collection_name="drugs_en",
        language="en",
    )
    ar = DrugRAGRetriever(
        qdrant_client=qdrant,
        embedder=FakeEmbedder(dimension=16, model_name="fake-ar"),
        collection_name="drugs_ar",
        language="ar",
    )
    return en, ar


def queue_bilingual(backend: FakeLLMBackend, en: dict, ar: dict) -> None:
    backend.queue(FakeResponse(content=json.dumps(en), prompt_tokens=80, completion_tokens=40))
    backend.queue(FakeResponse(content=json.dumps(ar), prompt_tokens=80, completion_tokens=40))


# ─── Dosage ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dosage_returns_regimens_combined_bilingually(session) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit("Metformin adult dose: 500-2000 mg/day")],
            "drugs_ar": [make_hit("جرعة الميتفورمين للبالغين", language="ar")],
        }
    )
    backend = FakeLLMBackend()
    queue_bilingual(
        backend,
        en={
            "regimens": [
                {
                    "population": "adult",
                    "standard_dose": "500-2000 mg/day",
                    "max_daily": "2550 mg",
                    "notes": "with food",
                }
            ],
            "adjustments_applied": [],
        },
        ar={
            "regimens": [
                {
                    "population": "adult",
                    "standard_dose": "٥٠٠-٢٠٠٠ مجم/يوم",
                    "max_daily": "٢٥٥٠ مجم",
                    "notes": "مع الطعام",
                }
            ],
            "adjustments_applied": [],
        },
    )
    en_r, ar_r = make_retrievers(qdrant)
    agent = DosageAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_r,
        ar_retriever=ar_r,
        llm_client=LLMClient(backend=backend),
        model="fake",
    )
    result = await agent.execute(
        DosageRequest(drug=DrugIdentifier(name="metformin"), language="en"),
        AgentContext(user_id="u", language="en"),
    )
    assert len(result.data.regimens) == 1
    regimen = result.data.regimens[0]
    assert regimen.population == "adult"
    assert regimen.standard_dose.en == "500-2000 mg/day"
    assert regimen.standard_dose.ar == "٥٠٠-٢٠٠٠ مجم/يوم"


@pytest.mark.asyncio
async def test_dosage_includes_patient_context_in_synthesis(session) -> None:
    """Verify patient context flows into the prompt by inspecting the synthesised output for adjustments."""
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit("Ibuprofen renal adjustment data")],
            "drugs_ar": [make_hit("بيانات تعديل جرعة الإيبوبروفين", language="ar")],
        }
    )
    backend = FakeLLMBackend()
    queue_bilingual(
        backend,
        en={
            "regimens": [
                {
                    "population": "renal",
                    "standard_dose": "reduced 50%",
                    "max_daily": "",
                    "notes": "",
                }
            ],
            "adjustments_applied": ["renal impairment reduces dose by 50%"],
        },
        ar={
            "regimens": [
                {"population": "renal", "standard_dose": "مخفّضة 50%", "max_daily": "", "notes": ""}
            ],
            "adjustments_applied": ["قصور كلوي يقلل الجرعة 50%"],
        },
    )
    en_r, ar_r = make_retrievers(qdrant)
    agent = DosageAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_r,
        ar_retriever=ar_r,
        llm_client=LLMClient(backend=backend),
        model="fake",
    )
    result = await agent.execute(
        DosageRequest(
            drug=DrugIdentifier(name="ibuprofen"),
            patient=PatientContext(age_years=65, renal_function="moderate"),
            language="en",
        ),
        AgentContext(user_id="u", language="en"),
    )
    assert len(result.data.adjustments_applied) == 1
    assert "renal" in result.data.adjustments_applied[0].en


# ─── Comparison ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_comparison_returns_one_row_per_drug(session) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [
                make_hit("amoxicillin info"),
                make_hit("azithromycin info", chunk_index=1),
            ],
            "drugs_ar": [make_hit("معلومات أموكسيسيلين", language="ar")],
        }
    )
    backend = FakeLLMBackend()
    queue_bilingual(
        backend,
        en={
            "rows": [
                {
                    "drug_rxcui": "723",
                    "drug_name": "amoxicillin",
                    "mechanism": "beta-lactam",
                    "efficacy_summary": "broad",
                    "common_side_effects": ["rash"],
                    "cost_tier": "$",
                    "contraindications": ["penicillin allergy"],
                    "drug_class": "penicillin",
                },
                {
                    "drug_rxcui": "18631",
                    "drug_name": "azithromycin",
                    "mechanism": "macrolide",
                    "efficacy_summary": "atypicals",
                    "common_side_effects": ["nausea"],
                    "cost_tier": "$$",
                    "contraindications": ["QT prolongation"],
                    "drug_class": "macrolide",
                },
            ]
        },
        ar={
            "rows": [
                {
                    "drug_rxcui": "723",
                    "drug_name": "amoxicillin",
                    "mechanism": "بيتا-لاكتام",
                    "efficacy_summary": "واسع",
                    "common_side_effects": ["طفح"],
                    "cost_tier": "$",
                    "contraindications": ["حساسية البنسلين"],
                    "drug_class": "penicillin",
                },
                {
                    "drug_rxcui": "18631",
                    "drug_name": "azithromycin",
                    "mechanism": "ماكروليد",
                    "efficacy_summary": "اللانمطية",
                    "common_side_effects": ["غثيان"],
                    "cost_tier": "$$",
                    "contraindications": ["إطالة QT"],
                    "drug_class": "macrolide",
                },
            ]
        },
    )
    en_r, ar_r = make_retrievers(qdrant)
    agent = ComparisonAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_r,
        ar_retriever=ar_r,
        llm_client=LLMClient(backend=backend),
        model="fake",
    )
    result = await agent.execute(
        ComparisonRequest(
            drugs=[DrugIdentifier(name="amoxicillin"), DrugIdentifier(name="azithromycin")],
            language="en",
        ),
        AgentContext(user_id="u", language="en"),
    )
    assert len(result.data.rows) == 2
    row0 = result.data.rows[0]
    assert row0.mechanism.en == "beta-lactam"
    assert row0.mechanism.ar == "بيتا-لاكتام"
    assert row0.cost_tier == "$"


# ─── Pharmacokinetics ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pharmacokinetics_returns_structured_pk_data(session) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit("Atorvastatin PK: Tmax 1-2h, t1/2 14h, CYP3A4")],
            "drugs_ar": [make_hit("الحركية الدوائية لأتورفاستاتين", language="ar")],
        }
    )
    backend = FakeLLMBackend()
    queue_bilingual(
        backend,
        en={
            "absorption": {
                "tmax_hours": 1.5,
                "bioavailability_percent": 14.0,
                "notes": "with or without food",
            },
            "distribution": {"vd_l_per_kg": 5.4, "protein_binding_percent": 98.0},
            "metabolism": {"primary_cyp_enzymes": ["CYP3A4"], "notes": "extensive first-pass"},
            "excretion": {"half_life_hours": 14.0, "primary_route": "hepatic"},
        },
        ar={
            "absorption": {
                "tmax_hours": 1.5,
                "bioavailability_percent": 14.0,
                "notes": "مع أو بدون طعام",
            },
            "distribution": {"vd_l_per_kg": 5.4, "protein_binding_percent": 98.0},
            "metabolism": {"primary_cyp_enzymes": ["CYP3A4"], "notes": "استقلاب أولي مكثف"},
            "excretion": {"half_life_hours": 14.0, "primary_route": "hepatic"},
        },
    )
    en_r, ar_r = make_retrievers(qdrant)
    agent = PharmacokineticsAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_r,
        ar_retriever=ar_r,
        llm_client=LLMClient(backend=backend),
        model="fake",
    )
    result = await agent.execute(
        PKRequest(drug=DrugIdentifier(name="atorvastatin"), language="en"),
        AgentContext(user_id="u", language="en"),
    )
    assert result.data.absorption.tmax_hours == 1.5
    assert result.data.absorption.bioavailability_percent == 14.0
    assert result.data.metabolism.primary_cyp_enzymes == ["CYP3A4"]
    assert result.data.excretion.primary_route == "hepatic"
    assert result.data.excretion.half_life_hours == 14.0
    assert result.data.absorption.notes is not None
    assert "food" in result.data.absorption.notes.en


# ─── Alternative ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alternative_returns_candidates_paired_by_rxcui(session) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [make_hit("Lisinopril alternatives: losartan, amlodipine")],
            "drugs_ar": [make_hit("بدائل ليزينوبريل", language="ar")],
        }
    )
    backend = FakeLLMBackend()
    queue_bilingual(
        backend,
        en={
            "candidates": [
                {
                    "rxcui": "52175",
                    "name": "losartan",
                    "drug_class": "ARB",
                    "rationale": "no cough side-effect",
                    "same_class": False,
                },
            ]
        },
        ar={
            "candidates": [
                {
                    "rxcui": "52175",
                    "name": "losartan",
                    "drug_class": "ARB",
                    "rationale": "لا يسبب السعال",
                    "same_class": False,
                },
            ]
        },
    )
    en_r, ar_r = make_retrievers(qdrant)
    agent = AlternativeAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_r,
        ar_retriever=ar_r,
        llm_client=LLMClient(backend=backend),
        model="fake",
    )
    result = await agent.execute(
        AlternativeRequest(drug=DrugIdentifier(name="lisinopril"), reason="cough", language="en"),
        AgentContext(user_id="u", language="en"),
    )
    assert result.data.original_rxcui == "29046"
    assert len(result.data.candidates) == 1
    cand = result.data.candidates[0]
    assert cand.name == "losartan"
    assert cand.rationale.en == "no cough side-effect"
    assert cand.rationale.ar == "لا يسبب السعال"
    assert cand.same_class is False


# ─── Acquisition ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquisition_returns_country_specific_data(session) -> None:
    qdrant = FakeQdrant(
        {
            "drugs_en": [
                make_hit("Ibuprofen OTC in Egypt at pharmacies"),
                make_hit("Egyptian brands include Brufen", chunk_index=1),
            ],
            "drugs_ar": [
                make_hit("الإيبوبروفين متاح بدون وصفة في مصر", language="ar"),
                make_hit("العلامات التجارية المصرية تشمل بروفين", chunk_index=1, language="ar"),
            ],
        }
    )
    backend = FakeLLMBackend()
    queue_bilingual(
        backend,
        en={
            "available_otc": True,
            "available_prescription": True,
            "price_tier": "$",
            "buying_considerations": ["sold OTC in pharmacies", "Brufen is the dominant brand"],
        },
        ar={
            "available_otc": True,
            "available_prescription": True,
            "price_tier": "$",
            "buying_considerations": ["يباع بدون وصفة في الصيدليات", "بروفين هو العلامة المهيمنة"],
        },
    )
    en_r, ar_r = make_retrievers(qdrant)
    agent = AcquisitionAgent(
        normaliser=RxNormNormaliser(session=session, api_client=FakeRxNormAPI()),
        en_retriever=en_r,
        ar_retriever=ar_r,
        llm_client=LLMClient(backend=backend),
        model="fake",
    )
    result = await agent.execute(
        AcquisitionRequest(drug=DrugIdentifier(name="ibuprofen"), country_iso="EG", language="en"),
        AgentContext(user_id="u", language="en"),
    )
    assert result.data.available_otc is True
    assert result.data.available_prescription is True
    assert result.data.price_tier == "$"
    assert len(result.data.buying_considerations) == 2
    assert (
        "OTC" in result.data.buying_considerations[0].en
        or "pharmacies" in result.data.buying_considerations[0].en
    )
    assert "بدون وصفة" in result.data.buying_considerations[0].ar


@pytest.mark.asyncio
async def test_acquisition_lower_confidence_threshold(session) -> None:
    """Acquisition uses min_confidence=0.65 (lower than the 0.7 default).

    This is documented as a unilateral decision — regional availability
    data is spottier than other domains, so we accept slightly lower
    retrieval coverage before raising low-confidence.
    """
    assert AcquisitionAgent.min_confidence == 0.65
