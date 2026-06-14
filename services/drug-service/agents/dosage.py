"""Dosage agent — patient-context-aware dosing recommendations."""

from __future__ import annotations

import asyncio
from itertools import zip_longest
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
from services.drug_service.agents.base import (
    DOSAGE_DISCLAIMER,
    AgentContext,
    AgentRunResult,
    BaseAgent,
)
from services.drug_service.exceptions import DrugNotFoundException
from services.drug_service.models.schemas import (
    BilingualText,
    Citation,
    DosageData,
    DosageRegimen,
    DosageRequest,
    Language,
    NormalisedDrug,
    PatientContext,
)
from services.drug_service.normalization import RxNormNormaliser
from shared.llm_client import LLMClient

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_TOP_K = 5
PROMPTS_DIR = Path(__file__).parent / "prompts"


class _LLMRegimen(BaseModel):
    population: Literal["adult", "pediatric", "elderly", "renal", "hepatic"]
    standard_dose: str = ""
    max_daily: str = ""
    notes: str = ""


class _LLMDosageResponse(BaseModel):
    regimens: list[_LLMRegimen] = Field(default_factory=list)
    adjustments_applied: list[str] = Field(default_factory=list)


class DosageAgent(BaseAgent[DosageRequest, DosageData]):
    name = "dosage"
    min_confidence = 0.7
    disclaimer = DOSAGE_DISCLAIMER

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
        self._en_retriever = en_retriever
        self._ar_retriever = ar_retriever
        self._llm = llm_client
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(
        self, request: DosageRequest, context: AgentContext
    ) -> AgentRunResult[DosageData]:
        drug = await self._normalise(request)
        query = drug.generic_name + " dosage adult pediatric"
        en_chunks, ar_chunks = await asyncio.gather(
            self._en_retriever.search(query, top_k=self._top_k),
            self._ar_retriever.search(query, top_k=self._top_k),
        )
        patient_block = self._format_patient(request.patient)
        (en_data, en_tokens), (ar_data, ar_tokens) = await asyncio.gather(
            self._synthesise(drug, en_chunks, patient_block, "en"),
            self._synthesise(drug, ar_chunks, patient_block, "ar"),
        )

        regimens = self._combine_regimens(en_data, ar_data)
        adjustments = [
            BilingualText(en=e or "", ar=a or "")
            for e, a in zip_longest(
                en_data.adjustments_applied, ar_data.adjustments_applied, fillvalue=""
            )
            if (e or a)
        ]
        data = DosageData(regimens=regimens, adjustments_applied=adjustments)
        confidence = self._compute_confidence(en_chunks, ar_chunks)
        citations = self._build_citations(en_chunks, ar_chunks)
        return AgentRunResult(
            data=data,
            citations=citations,
            confidence=confidence,
            tokens_used=en_tokens + ar_tokens,
        )

    async def _normalise(self, request: DosageRequest) -> NormalisedDrug:
        ref = request.drug.name or request.drug.rxcui
        if not ref:
            raise DrugNotFoundException("DrugIdentifier requires either name or rxcui")
        return await self._normaliser.resolve(ref)

    def _format_patient(self, patient: PatientContext) -> str:
        parts: list[str] = []
        if patient.age_years is not None:
            parts.append(f"age: {patient.age_years} years")
        if patient.weight_kg is not None:
            parts.append(f"weight: {patient.weight_kg} kg")
        if patient.renal_function:
            parts.append(f"renal: {patient.renal_function} impairment")
        if patient.hepatic_function:
            parts.append(f"hepatic: {patient.hepatic_function} impairment")
        if patient.pregnancy is True:
            parts.append("pregnancy: yes")
        if patient.conditions:
            parts.append(f"conditions: {', '.join(patient.conditions)}")
        return "\n".join(f"- {p}" for p in parts) if parts else "(no patient context supplied)"

    async def _synthesise(
        self,
        drug: NormalisedDrug,
        chunks: list[RetrievedChunk],
        patient_block: str,
        language: Language,
    ) -> tuple[_LLMDosageResponse, int]:
        if not chunks:
            return _LLMDosageResponse(), 0
        template = load_prompt(self._prompts_dir, "dosage", language)
        user_prompt = format_prompt(
            template,
            generic_name=drug.generic_name,
            brand_names=", ".join(drug.brand_names) or "(none on file)",
            drug_class=drug.drug_class or "(unknown)",
            rxcui=drug.rxcui,
            patient_context=patient_block,
            chunks=build_chunk_context(chunks),
        )
        system = (
            "You return ONLY JSON. No prose, no markdown."
            if language == "en"
            else "أنت تنتج JSON فقط. بدون نثر، بدون markdown."
        )
        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system,
            user_prompt=user_prompt,
            schema=_LLMDosageResponse,
            max_tokens=1000,
        )

    def _combine_regimens(
        self, en: _LLMDosageResponse, ar: _LLMDosageResponse
    ) -> list[DosageRegimen]:
        # Match by population — same population in en and ar pair up.
        ar_by_pop = {r.population: r for r in ar.regimens}
        out: list[DosageRegimen] = []
        for en_r in en.regimens:
            ar_r = ar_by_pop.get(en_r.population)
            out.append(
                DosageRegimen(
                    population=en_r.population,
                    standard_dose=BilingualText(
                        en=en_r.standard_dose, ar=(ar_r.standard_dose if ar_r else "")
                    ),
                    max_daily=(
                        BilingualText(en=en_r.max_daily, ar=(ar_r.max_daily if ar_r else ""))
                        if (en_r.max_daily or (ar_r and ar_r.max_daily))
                        else None
                    ),
                    notes=(
                        BilingualText(en=en_r.notes, ar=(ar_r.notes if ar_r else ""))
                        if (en_r.notes or (ar_r and ar_r.notes))
                        else None
                    ),
                )
            )
        # Add ar-only populations (rare, but possible)
        en_pops = {r.population for r in en.regimens}
        for ar_r in ar.regimens:
            if ar_r.population in en_pops:
                continue
            out.append(
                DosageRegimen(
                    population=ar_r.population,
                    standard_dose=BilingualText(en="", ar=ar_r.standard_dose),
                    max_daily=BilingualText(en="", ar=ar_r.max_daily) if ar_r.max_daily else None,
                    notes=BilingualText(en="", ar=ar_r.notes) if ar_r.notes else None,
                )
            )
        return out

    def _compute_confidence(
        self, en_chunks: list[RetrievedChunk], ar_chunks: list[RetrievedChunk]
    ) -> float:
        if not en_chunks and not ar_chunks:
            return 0.3
        if not en_chunks or not ar_chunks:
            return 0.6
        return max(0.7, min(1.0, mean([en_chunks[0].score, ar_chunks[0].score])))

    def _build_citations(
        self, en_chunks: list[RetrievedChunk], ar_chunks: list[RetrievedChunk]
    ) -> list[Citation]:
        seen: set[tuple[str, int]] = set()
        out: list[Citation] = []
        for chunk in (*en_chunks, *ar_chunks):
            key = (chunk.sha256, chunk.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            out.append(chunk.to_citation())
        return out


__all__ = ["DosageAgent"]
