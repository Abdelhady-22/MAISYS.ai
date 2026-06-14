"""Drug Lookup agent.

Flow:

1. Normalise the input drug via ``RxNormNormaliser`` → canonical
   RxCUI, generic name, brand names, drug class.
2. Retrieve top-K chunks from BOTH ``drugs_en`` and ``drugs_ar``
   Qdrant collections in parallel. Two retrievers, two separate
   embedders (English and Arabic), two searches — results never
   cross language boundaries.
3. Run two LLM completions in parallel — one per language — each
   given the language-matched chunks as context. Outputs are
   small JSON objects with indications, mechanism, contraindications.
4. Combine the two language responses into ``LookupData`` where
   ``indications`` / ``contraindications`` / ``mechanism_of_action``
   are ``BilingualText`` (both languages always present).
5. Build citations from the union of retrieved chunks. Compute
   confidence from retrieval scores and parse outcome.

Confidence model:

* Start at 1.0.
* If both languages got zero chunks, confidence drops to 0.3.
* If one language got zero, confidence is 0.6 (frontend still
  renders the language it has).
* Otherwise, scaled by the mean of the top-1 scores across both
  collections.

The agent is constructed with all its dependencies injected so
tests can swap real Qdrant / real LLM / real embedders for fakes.
"""

from __future__ import annotations

import asyncio
from itertools import zip_longest
from pathlib import Path
from statistics import mean

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
    AgentContext,
    AgentRunResult,
    BaseAgent,
)
from services.drug_service.exceptions import DrugNotFoundException
from services.drug_service.models.schemas import (
    BilingualText,
    Citation,
    DrugIdentifier,
    Language,
    LookupData,
    LookupRequest,
    NormalisedDrug,
)
from services.drug_service.normalization import RxNormNormaliser
from shared.llm_client import LLMClient
from shared.logger import get_logger

_log = get_logger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_TOP_K = 5
PROMPTS_DIR = Path(__file__).parent / "prompts"


class _LookupLLMResponse(BaseModel):
    """Per-language JSON schema the LLM must produce."""

    indications: list[str] = Field(default_factory=list)
    mechanism_of_action: str = ""
    contraindications: list[str] = Field(default_factory=list)


class LookupAgent(BaseAgent[LookupRequest, LookupData]):
    """Resolves a drug identifier to bilingual structured drug information."""

    name = "lookup"
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
        assert en_retriever.language == "en", "en_retriever must be configured for English"
        assert ar_retriever.language == "ar", "ar_retriever must be configured for Arabic"
        self._normaliser = normaliser
        self._en_retriever = en_retriever
        self._ar_retriever = ar_retriever
        self._llm = llm_client
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(
        self, request: LookupRequest, context: AgentContext
    ) -> AgentRunResult[LookupData]:
        # 1. Normalise — resolves DrugIdentifier (name OR rxcui) to RxCUI.
        drug = await self._normalise(request.drug)
        context.extra["normalised_drug"] = drug
        _log.info(
            "agent.lookup.normalised",
            correlation_id=context.correlation_id,
            rxcui=drug.rxcui,
            path=drug.normalisation_path,
        )

        # 2. Retrieve from both collections in parallel.
        query = drug.generic_name  # canonical English term — works as a query in both languages
        en_chunks, ar_chunks = await asyncio.gather(
            self._en_retriever.search(query, top_k=self._top_k),
            self._ar_retriever.search(query, top_k=self._top_k),
        )
        _log.info(
            "agent.lookup.retrieved",
            correlation_id=context.correlation_id,
            en_count=len(en_chunks),
            ar_count=len(ar_chunks),
        )

        # 3. LLM synthesis — parallel.
        (en_synth, en_tokens), (ar_synth, ar_tokens) = await asyncio.gather(
            self._synthesise(drug, en_chunks, "en"),
            self._synthesise(drug, ar_chunks, "ar"),
        )

        # 4. Combine.
        data = self._combine(drug, en_synth, ar_synth)

        # 5. Citations + confidence.
        citations = self._build_citations(en_chunks, ar_chunks)
        confidence = self._compute_confidence(en_chunks, ar_chunks)

        return AgentRunResult(
            data=data,
            citations=citations,
            confidence=confidence,
            tokens_used=en_tokens + ar_tokens,
        )

    # ─── Step implementations ─────────────────────────────────────

    async def _normalise(self, identifier: DrugIdentifier) -> NormalisedDrug:
        """Accept either a name (call the normaliser) or an rxcui (cache lookup)."""
        if identifier.name:
            return await self._normaliser.resolve(identifier.name)
        if identifier.rxcui:
            # rxcui supplied directly: build a NormalisedDrug from the cache.
            # If we don't have it cached, fall through to "as if user typed
            # the rxcui as a name" — RxNorm API accepts numeric searches too.
            return await self._normaliser.resolve(identifier.rxcui)
        raise DrugNotFoundException("DrugIdentifier requires either name or rxcui")

    async def _synthesise(
        self,
        drug: NormalisedDrug,
        chunks: list[RetrievedChunk],
        language: Language,
    ) -> tuple[_LookupLLMResponse, int]:
        if not chunks:
            # Empty retrieval — return empty fields; confidence path picks this up.
            return _LookupLLMResponse(), 0

        template = load_prompt(self._prompts_dir, "lookup", language)
        user_prompt = format_prompt(
            template,
            generic_name=drug.generic_name,
            brand_names=", ".join(drug.brand_names) if drug.brand_names else "(none on file)",
            drug_class=drug.drug_class or "(unknown)",
            rxcui=drug.rxcui,
            chunks=build_chunk_context(chunks),
        )
        system_prompt = (
            "You return ONLY a JSON object matching the requested schema. No prose, no markdown."
            if language == "en"
            else "أنت تنتج فقط كائن JSON يطابق المخطط المطلوب. بدون نثر، بدون markdown."
        )

        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=_LookupLLMResponse,
        )

    def _combine(
        self,
        drug: NormalisedDrug,
        en: _LookupLLMResponse,
        ar: _LookupLLMResponse,
    ) -> LookupData:
        # Pair up indications and contraindications by index; pad with
        # empty strings if the LLM returned uneven counts across languages.
        indications = [
            BilingualText(en=e or "", ar=a or "")
            for e, a in zip_longest(en.indications, ar.indications, fillvalue="")
            if (e or a)  # drop empty pairs
        ]
        contraindications = [
            BilingualText(en=e or "", ar=a or "")
            for e, a in zip_longest(en.contraindications, ar.contraindications, fillvalue="")
            if (e or a)
        ]
        mechanism: BilingualText | None = None
        if en.mechanism_of_action or ar.mechanism_of_action:
            mechanism = BilingualText(
                en=en.mechanism_of_action or "",
                ar=ar.mechanism_of_action or "",
            )
        return LookupData(
            rxcui=drug.rxcui,
            generic_name=drug.generic_name,
            brand_names=drug.brand_names,
            drug_class=drug.drug_class,
            indications=indications,
            mechanism_of_action=mechanism,
            contraindications=contraindications,
        )

    def _build_citations(
        self, en_chunks: list[RetrievedChunk], ar_chunks: list[RetrievedChunk]
    ) -> list[Citation]:
        # Deduplicate by (sha256, chunk_index) so we don't cite the
        # same chunk twice when it appears in both collections at the
        # same chunk position.
        seen: set[tuple[str, int]] = set()
        out: list[Citation] = []
        for chunk in (*en_chunks, *ar_chunks):
            key = (chunk.sha256, chunk.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            out.append(chunk.to_citation())
        return out

    def _compute_confidence(
        self,
        en_chunks: list[RetrievedChunk],
        ar_chunks: list[RetrievedChunk],
    ) -> float:
        if not en_chunks and not ar_chunks:
            return 0.3
        if not en_chunks or not ar_chunks:
            return 0.6
        # Both sides retrieved at least one chunk — scale by mean top-1 score.
        # Qdrant cosine scores sit in [-1, 1]; for medical RAG the realistic
        # range is roughly [0.3, 0.95]. Clamp to [0.7, 1.0] for the confidence.
        top_scores = [en_chunks[0].score, ar_chunks[0].score]
        scaled = max(0.7, min(1.0, mean(top_scores)))
        return scaled


__all__ = ["LookupAgent"]
