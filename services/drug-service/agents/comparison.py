"""Comparison agent — side-by-side drug comparison."""

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
    BilingualText,
    Citation,
    ComparisonData,
    ComparisonRequest,
    ComparisonRow,
    DrugIdentifier,
    Language,
    NormalisedDrug,
)
from services.drug_service.normalization import RxNormNormaliser
from shared.llm_client import LLMClient

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_TOP_K = 3
PROMPTS_DIR = Path(__file__).parent / "prompts"


class _LLMRow(BaseModel):
    drug_rxcui: str
    drug_name: str
    mechanism: str = ""
    efficacy_summary: str = ""
    common_side_effects: list[str] = Field(default_factory=list)
    cost_tier: Literal["$", "$$", "$$$", "$$$$"] = "$$"
    contraindications: list[str] = Field(default_factory=list)
    drug_class: str | None = None


class _LLMResp(BaseModel):
    rows: list[_LLMRow] = Field(default_factory=list)


class ComparisonAgent(BaseAgent[ComparisonRequest, ComparisonData]):
    name = "comparison"
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
        self._en_retriever = en_retriever
        self._ar_retriever = ar_retriever
        self._llm = llm_client
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(
        self, request: ComparisonRequest, context: AgentContext
    ) -> AgentRunResult[ComparisonData]:
        drugs = await self._normalise_all(request.drugs)
        drug_table = "\n".join(
            f"- {d.generic_name} (class: {d.drug_class or 'unknown'}, RxCUI: {d.rxcui})"
            for d in drugs
        )
        # Retrieve per-drug context, combine.
        all_en: list[RetrievedChunk] = []
        all_ar: list[RetrievedChunk] = []
        for drug in drugs:
            en, ar = await asyncio.gather(
                self._en_retriever.search(drug.generic_name, top_k=self._top_k),
                self._ar_retriever.search(drug.generic_name, top_k=self._top_k),
            )
            all_en.extend(en)
            all_ar.extend(ar)

        (en_resp, en_tokens), (ar_resp, ar_tokens) = await asyncio.gather(
            self._synthesise(drug_table, all_en, "en"),
            self._synthesise(drug_table, all_ar, "ar"),
        )
        rows = self._combine(drugs, en_resp, ar_resp)
        confidence = self._compute_confidence(all_en, all_ar)
        return AgentRunResult(
            data=ComparisonData(rows=rows),
            citations=self._build_citations(all_en + all_ar),
            confidence=confidence,
            tokens_used=en_tokens + ar_tokens,
        )

    async def _normalise_all(self, identifiers: list[DrugIdentifier]) -> list[NormalisedDrug]:
        async def _one(i: DrugIdentifier) -> NormalisedDrug:
            ref = i.name or i.rxcui
            if not ref:
                raise DrugNotFoundException("DrugIdentifier requires name or rxcui")
            return await self._normaliser.resolve(ref)

        return await asyncio.gather(*[_one(d) for d in identifiers])

    async def _synthesise(
        self, drug_table: str, chunks: list[RetrievedChunk], language: Language
    ) -> tuple[_LLMResp, int]:
        if not chunks:
            return _LLMResp(), 0
        template = load_prompt(self._prompts_dir, "compare", language)
        user_prompt = format_prompt(
            template, drug_table=drug_table, chunks=build_chunk_context(chunks)
        )
        system = "You return ONLY JSON. No prose, no markdown."
        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system,
            user_prompt=user_prompt,
            schema=_LLMResp,
            max_tokens=1500,
        )

    def _combine(
        self, drugs: list[NormalisedDrug], en: _LLMResp, ar: _LLMResp
    ) -> list[ComparisonRow]:
        ar_by_rxcui = {r.drug_rxcui: r for r in ar.rows}
        out: list[ComparisonRow] = []
        for en_r in en.rows:
            ar_r = ar_by_rxcui.get(en_r.drug_rxcui)
            out.append(
                ComparisonRow(
                    drug_rxcui=en_r.drug_rxcui,
                    drug_name=en_r.drug_name,
                    mechanism=BilingualText(en=en_r.mechanism, ar=(ar_r.mechanism if ar_r else "")),
                    efficacy_summary=BilingualText(
                        en=en_r.efficacy_summary, ar=(ar_r.efficacy_summary if ar_r else "")
                    ),
                    common_side_effects=[
                        BilingualText(
                            en=e,
                            ar=(
                                ar_r.common_side_effects[i]
                                if ar_r and i < len(ar_r.common_side_effects)
                                else ""
                            ),
                        )
                        for i, e in enumerate(en_r.common_side_effects)
                    ],
                    cost_tier=en_r.cost_tier,
                    contraindications=[
                        BilingualText(
                            en=e,
                            ar=(
                                ar_r.contraindications[i]
                                if ar_r and i < len(ar_r.contraindications)
                                else ""
                            ),
                        )
                        for i, e in enumerate(en_r.contraindications)
                    ],
                    drug_class=en_r.drug_class,
                )
            )
        return out

    def _compute_confidence(self, en: list[RetrievedChunk], ar: list[RetrievedChunk]) -> float:
        if not en and not ar:
            return 0.3
        if not en or not ar:
            return 0.6
        return max(0.7, min(1.0, mean([en[0].score, ar[0].score])))

    def _build_citations(self, chunks: list[RetrievedChunk]) -> list[Citation]:
        seen: set[tuple[str, int]] = set()
        out: list[Citation] = []
        for chunk in chunks:
            key = (chunk.sha256, chunk.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            out.append(chunk.to_citation())
        return out


__all__ = ["ComparisonAgent"]
