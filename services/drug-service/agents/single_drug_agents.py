"""Pharmacokinetics, Alternative, and Acquisition agents — single-drug agents that share the normalise → retrieve → synthesise → bilingual-combine flow.

These three agents are structurally identical to ``DosageAgent`` and
``LookupAgent``: each takes a single drug, retrieves bilingual chunks,
runs two parallel LLM completions, combines into a bilingual response.
They are co-located in one file because each is small and the
duplication-cost would exceed the navigation-cost otherwise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, Field

from services.drug_service.agents._llm_helpers import (
    format_prompt,
    load_prompt,
    synthesise_json,
)
from services.drug_service.agents._retrieval import (
    DrugRAGRetriever,
    RetrievedChunk,
    build_chunk_context,
)
from services.drug_service.agents.base import AgentContext, AgentRunResult, BaseAgent
from services.drug_service.exceptions import DrugNotFoundException
from services.drug_service.models.schemas import (
    AbsorptionData,
    AcquisitionData,
    AcquisitionRequest,
    AlternativeCandidate,
    AlternativeData,
    AlternativeRequest,
    BilingualText,
    Citation,
    DistributionData,
    ExcretionData,
    Language,
    MetabolismData,
    NormalisedDrug,
    PKData,
    PKRequest,
)
from services.drug_service.normalization import RxNormNormaliser
from shared.llm_client import LLMClient

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_TOP_K = 5
PROMPTS_DIR = Path(__file__).parent / "prompts"


# ─── helpers shared across the three agents ───────────────────────


async def _normalise_one(
    normaliser: RxNormNormaliser, name: str | None, rxcui: str | None
) -> NormalisedDrug:
    ref = name or rxcui
    if not ref:
        raise DrugNotFoundException("DrugIdentifier requires name or rxcui")
    return await normaliser.resolve(ref)


def _confidence(en: list[RetrievedChunk], ar: list[RetrievedChunk]) -> float:
    if not en and not ar:
        return 0.3
    if not en or not ar:
        return 0.6
    return max(0.7, min(1.0, mean([en[0].score, ar[0].score])))


def _dedup_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    seen: set[tuple[str, int]] = set()
    out: list[Citation] = []
    for chunk in chunks:
        key = (chunk.sha256, chunk.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk.to_citation())
    return out


# ─── Pharmacokinetics ─────────────────────────────────────────────


class _LLMAbsorption(BaseModel):
    tmax_hours: float | None = None
    bioavailability_percent: float | None = None
    notes: str = ""


class _LLMDistribution(BaseModel):
    vd_l_per_kg: float | None = None
    protein_binding_percent: float | None = None


class _LLMMetabolism(BaseModel):
    primary_cyp_enzymes: list[str] = Field(default_factory=list)
    notes: str = ""


class _LLMExcretion(BaseModel):
    half_life_hours: float | None = None
    primary_route: Literal["renal", "hepatic", "fecal", "mixed"] | None = None


class _LLMPKResp(BaseModel):
    absorption: _LLMAbsorption = Field(default_factory=_LLMAbsorption)
    distribution: _LLMDistribution = Field(default_factory=_LLMDistribution)
    metabolism: _LLMMetabolism = Field(default_factory=_LLMMetabolism)
    excretion: _LLMExcretion = Field(default_factory=_LLMExcretion)


class PharmacokineticsAgent(BaseAgent[PKRequest, PKData]):
    name = "pharmacokinetics"
    min_confidence = 0.7

    def __init__(
        self,
        *,
        normaliser: RxNormNormaliser,
        en_retriever: DrugRAGRetriever,
        ar_retriever: DrugRAGRetriever,
        llm_client: LLMClient,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        prompts_dir: Path | None = None,
    ) -> None:
        self._normaliser = normaliser
        self._en = en_retriever
        self._ar = ar_retriever
        self._llm = llm_client
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(self, request: PKRequest, context: AgentContext) -> AgentRunResult[PKData]:
        drug = await _normalise_one(self._normaliser, request.drug.name, request.drug.rxcui)
        query = f"{drug.generic_name} pharmacokinetics absorption metabolism excretion"
        en_chunks, ar_chunks = await asyncio.gather(
            self._en.search(query, top_k=self._top_k),
            self._ar.search(query, top_k=self._top_k),
        )
        (en, en_tokens), (ar, ar_tokens) = await asyncio.gather(
            self._synthesise(drug, en_chunks, "en"),
            self._synthesise(drug, ar_chunks, "ar"),
        )

        # Combine — bilingual notes; numeric fields prefer en (canonical clinical data).
        data = PKData(
            absorption=AbsorptionData(
                tmax_hours=en.absorption.tmax_hours,
                bioavailability_percent=en.absorption.bioavailability_percent,
                notes=(
                    BilingualText(en=en.absorption.notes, ar=ar.absorption.notes)
                    if (en.absorption.notes or ar.absorption.notes)
                    else None
                ),
            ),
            distribution=DistributionData(
                vd_l_per_kg=en.distribution.vd_l_per_kg,
                protein_binding_percent=en.distribution.protein_binding_percent,
            ),
            metabolism=MetabolismData(
                primary_cyp_enzymes=en.metabolism.primary_cyp_enzymes,
                notes=(
                    BilingualText(en=en.metabolism.notes, ar=ar.metabolism.notes)
                    if (en.metabolism.notes or ar.metabolism.notes)
                    else None
                ),
            ),
            excretion=ExcretionData(
                half_life_hours=en.excretion.half_life_hours,
                primary_route=en.excretion.primary_route,
            ),
        )
        return AgentRunResult(
            data=data,
            citations=_dedup_citations(en_chunks + ar_chunks),
            confidence=_confidence(en_chunks, ar_chunks),
            tokens_used=en_tokens + ar_tokens,
        )

    async def _synthesise(
        self, drug: NormalisedDrug, chunks: list[RetrievedChunk], language: Language
    ) -> tuple[_LLMPKResp, int]:
        if not chunks:
            return _LLMPKResp(), 0
        template = load_prompt(self._prompts_dir, "pharmacokinetics", language)
        user_prompt = format_prompt(
            template,
            generic_name=drug.generic_name,
            rxcui=drug.rxcui,
            drug_class=drug.drug_class or "(unknown)",
            chunks=build_chunk_context(chunks),
        )
        system = "You return ONLY JSON. No prose, no markdown."
        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system,
            user_prompt=user_prompt,
            schema=_LLMPKResp,
        )


# ─── Alternative ──────────────────────────────────────────────────


class _LLMCandidate(BaseModel):
    rxcui: str
    name: str
    drug_class: str | None = None
    rationale: str = ""
    same_class: bool = False


class _LLMAltResp(BaseModel):
    candidates: list[_LLMCandidate] = Field(default_factory=list)


class AlternativeAgent(BaseAgent[AlternativeRequest, AlternativeData]):
    name = "alternative"
    min_confidence = 0.7

    def __init__(
        self,
        *,
        normaliser: RxNormNormaliser,
        en_retriever: DrugRAGRetriever,
        ar_retriever: DrugRAGRetriever,
        llm_client: LLMClient,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        prompts_dir: Path | None = None,
    ) -> None:
        self._normaliser = normaliser
        self._en = en_retriever
        self._ar = ar_retriever
        self._llm = llm_client
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(
        self, request: AlternativeRequest, context: AgentContext
    ) -> AgentRunResult[AlternativeData]:
        drug = await _normalise_one(self._normaliser, request.drug.name, request.drug.rxcui)
        query = f"{drug.generic_name} alternative {request.reason}"
        en_chunks, ar_chunks = await asyncio.gather(
            self._en.search(query, top_k=self._top_k),
            self._ar.search(query, top_k=self._top_k),
        )
        (en, en_tokens), (ar, ar_tokens) = await asyncio.gather(
            self._synthesise(drug, request.reason, en_chunks, "en"),
            self._synthesise(drug, request.reason, ar_chunks, "ar"),
        )

        # Pair candidates by rxcui across the two languages
        ar_by_rx = {c.rxcui: c for c in ar.candidates}
        candidates: list[AlternativeCandidate] = []
        for en_c in en.candidates:
            ar_c = ar_by_rx.get(en_c.rxcui)
            rationale = BilingualText(en=en_c.rationale, ar=(ar_c.rationale if ar_c else ""))
            candidates.append(
                AlternativeCandidate(
                    rxcui=en_c.rxcui,
                    name=en_c.name,
                    drug_class=en_c.drug_class,
                    rationale=rationale,
                    same_class=en_c.same_class,
                )
            )

        data = AlternativeData(original_rxcui=drug.rxcui, candidates=candidates)
        return AgentRunResult(
            data=data,
            citations=_dedup_citations(en_chunks + ar_chunks),
            confidence=_confidence(en_chunks, ar_chunks),
            tokens_used=en_tokens + ar_tokens,
        )

    async def _synthesise(
        self,
        drug: NormalisedDrug,
        reason: str,
        chunks: list[RetrievedChunk],
        language: Language,
    ) -> tuple[_LLMAltResp, int]:
        if not chunks:
            return _LLMAltResp(), 0
        template = load_prompt(self._prompts_dir, "alternatives", language)
        user_prompt = format_prompt(
            template,
            generic_name=drug.generic_name,
            rxcui=drug.rxcui,
            drug_class=drug.drug_class or "(unknown)",
            reason=reason,
            chunks=build_chunk_context(chunks),
        )
        system = "You return ONLY JSON. No prose, no markdown."
        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system,
            user_prompt=user_prompt,
            schema=_LLMAltResp,
        )


# ─── Acquisition ──────────────────────────────────────────────────


class _LLMAcqResp(BaseModel):
    available_otc: bool | None = None
    available_prescription: bool | None = None
    price_tier: Literal["$", "$$", "$$$", "$$$$"] | None = None
    buying_considerations: list[str] = Field(default_factory=list)


class AcquisitionAgent(BaseAgent[AcquisitionRequest, AcquisitionData]):
    name = "acquisition"
    min_confidence = 0.65  # availability data is regionally spotty — slightly lower threshold

    def __init__(
        self,
        *,
        normaliser: RxNormNormaliser,
        en_retriever: DrugRAGRetriever,
        ar_retriever: DrugRAGRetriever,
        llm_client: LLMClient,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        prompts_dir: Path | None = None,
    ) -> None:
        self._normaliser = normaliser
        self._en = en_retriever
        self._ar = ar_retriever
        self._llm = llm_client
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(
        self, request: AcquisitionRequest, context: AgentContext
    ) -> AgentRunResult[AcquisitionData]:
        drug = await _normalise_one(self._normaliser, request.drug.name, request.drug.rxcui)
        query = f"{drug.generic_name} availability OTC prescription {request.country_iso}"
        en_chunks, ar_chunks = await asyncio.gather(
            self._en.search(query, top_k=self._top_k),
            self._ar.search(query, top_k=self._top_k),
        )
        (en, en_tokens), (ar, ar_tokens) = await asyncio.gather(
            self._synthesise(drug, request.country_iso, en_chunks, "en"),
            self._synthesise(drug, request.country_iso, ar_chunks, "ar"),
        )

        # Boolean / tier fields: prefer en when set, otherwise ar.
        # Considerations: bilingual pair-up by index.
        considerations: list[BilingualText] = []
        max_len = max(len(en.buying_considerations), len(ar.buying_considerations))
        for i in range(max_len):
            en_text = en.buying_considerations[i] if i < len(en.buying_considerations) else ""
            ar_text = ar.buying_considerations[i] if i < len(ar.buying_considerations) else ""
            if en_text or ar_text:
                considerations.append(BilingualText(en=en_text, ar=ar_text))

        data = AcquisitionData(
            available_otc=en.available_otc if en.available_otc is not None else ar.available_otc,
            available_prescription=(
                en.available_prescription
                if en.available_prescription is not None
                else ar.available_prescription
            ),
            price_tier=en.price_tier or ar.price_tier,
            buying_considerations=considerations,
        )
        return AgentRunResult(
            data=data,
            citations=_dedup_citations(en_chunks + ar_chunks),
            confidence=_confidence(en_chunks, ar_chunks),
            tokens_used=en_tokens + ar_tokens,
        )

    async def _synthesise(
        self,
        drug: NormalisedDrug,
        country_iso: str,
        chunks: list[RetrievedChunk],
        language: Language,
    ) -> tuple[_LLMAcqResp, int]:
        if not chunks:
            return _LLMAcqResp(), 0
        template = load_prompt(self._prompts_dir, "acquisition", language)
        user_prompt = format_prompt(
            template,
            generic_name=drug.generic_name,
            rxcui=drug.rxcui,
            drug_class=drug.drug_class or "(unknown)",
            country_iso=country_iso,
            chunks=build_chunk_context(chunks),
        )
        system = "You return ONLY JSON. No prose, no markdown."
        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system,
            user_prompt=user_prompt,
            schema=_LLMAcqResp,
        )


__all__ = ["AcquisitionAgent", "AlternativeAgent", "PharmacokineticsAgent"]
