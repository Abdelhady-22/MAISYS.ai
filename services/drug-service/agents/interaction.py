"""Drug Interaction agent — tiered evidence retrieval.

Three escalating tiers:

* **Tier 0 (DDIMDL)** — canonical pair lookup in ``ddimdl_interactions``
  (PR1, P2-T01). The pair is checked in both orderings so
  ``(aspirin, warfarin)`` and ``(warfarin, aspirin)`` resolve the
  same way.
* **Tier 1 (drug_rag)** — for pairs without DDIMDL coverage, query
  the bilingual Qdrant collections (``drugs_en`` / ``drugs_ar``)
  with the natural-language query ``"<drug_a> <drug_b> interaction"``.
* **Tier 2 (web_search)** — for pairs still uncovered, call the
  injected ``WebSearchAgent``. If no agent was injected (commit 10
  ships it), this tier is skipped and the LLM is told the
  pair has no web evidence.

The agent's confidence reflects coverage: every pair found in DDIMDL
is high-confidence; pairs that escalated to RAG are medium; pairs
with no evidence anywhere are low and pull the overall confidence
down.

``overall_severity`` is the max across pairs in the ordering
``contraindicated > major > moderate > minor``.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

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
    INTERACTION_DISCLAIMER,
    AgentContext,
    AgentRunResult,
    BaseAgent,
)
from services.drug_service.exceptions import DrugNotFoundException
from services.drug_service.models.schemas import (
    BilingualText,
    Citation,
    DrugIdentifier,
    InteractionPair,
    InteractionsData,
    InteractionsRequest,
    Language,
    NormalisedDrug,
    Severity,
)
from services.drug_service.normalization import RxNormNormaliser
from shared.llm_client import LLMClient
from shared.logger import get_logger

# Imported lazily from data-pipeline at call time so this module
# doesn't take a hard dependency on a sibling package.

_log = get_logger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_TOP_K = 4
PROMPTS_DIR = Path(__file__).parent / "prompts"

SEVERITY_ORDER: dict[Severity, int] = {
    "minor": 0,
    "moderate": 1,
    "major": 2,
    "contraindicated": 3,
}


# ─── LLM output schema ────────────────────────────────────────────


class _LLMInteractionPair(BaseModel):
    drug_a: str
    drug_b: str
    severity: Severity
    description: str
    source_tier: str = "drug_rag"


class _LLMInteractionsResponse(BaseModel):
    pairs: list[_LLMInteractionPair] = Field(default_factory=list)


# ─── Tier-0 helper types ──────────────────────────────────────────


class _DDIMDLHit(BaseModel):
    drug_a: str
    drug_b: str
    interaction_text: str | None
    severity_code: str | None
    source_file: str

    def as_evidence_line(self) -> str:
        sev = self.severity_code or "(no severity)"
        text = self.interaction_text or "(no description)"
        return f"- {self.drug_a} ↔ {self.drug_b} [{sev}]: {text}"


# ─── WebSearchAgent protocol (commit 10 supplies the concrete) ────


class WebSearchAgentLike(Protocol):
    """Structural protocol — what InteractionAgent needs from a WebSearchAgent."""

    async def find_interaction(
        self, drug_a: str, drug_b: str, language: Language
    ) -> tuple[str, str] | None:
        """Return (description, source_url) or None when nothing found."""
        ...


# ─── Agent ────────────────────────────────────────────────────────


class InteractionAgent(BaseAgent[InteractionsRequest, InteractionsData]):
    """3-tier interaction check: DDIMDL → drug_rag → optional web search."""

    name = "interaction"
    min_confidence = 0.7
    disclaimer = INTERACTION_DISCLAIMER

    def __init__(
        self,
        *,
        normaliser: RxNormNormaliser,
        ddimdl_session_factory: async_sessionmaker[Any],
        en_retriever: DrugRAGRetriever,
        ar_retriever: DrugRAGRetriever,
        llm_client: LLMClient,
        web_search_agent: WebSearchAgentLike | None = None,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        prompts_dir: Path | None = None,
    ) -> None:
        self._normaliser = normaliser
        self._ddimdl_factory = ddimdl_session_factory
        self._en_retriever = en_retriever
        self._ar_retriever = ar_retriever
        self._llm = llm_client
        self._web_search = web_search_agent
        self._model = model
        self._top_k = top_k
        self._prompts_dir = prompts_dir or PROMPTS_DIR

    async def _run(
        self, request: InteractionsRequest, context: AgentContext
    ) -> AgentRunResult[InteractionsData]:
        # 1. Normalise every input drug
        drugs = await self._normalise_all(request.drugs)
        pairs = list(itertools.combinations(drugs, 2))
        _log.info(
            "agent.interaction.pairs",
            correlation_id=context.correlation_id,
            n_drugs=len(drugs),
            n_pairs=len(pairs),
        )

        # 2. Tier 0 — DDIMDL lookup
        ddimdl_hits = await self._query_ddimdl(pairs)
        ddimdl_covered = {self._pair_key(h.drug_a, h.drug_b) for h in ddimdl_hits}
        missing_pairs_t1 = [
            p
            for p in pairs
            if self._pair_key(p[0].generic_name, p[1].generic_name) not in ddimdl_covered
        ]

        # 3. Tier 1 — drug_rag (one combined retrieval per language)
        rag_en, rag_ar = await self._query_drug_rag(missing_pairs_t1)
        rag_covered = self._pairs_covered_by_chunks(missing_pairs_t1, rag_en + rag_ar)
        missing_pairs_t2 = [
            p
            for p in missing_pairs_t1
            if self._pair_key(p[0].generic_name, p[1].generic_name) not in rag_covered
        ]

        # 4. Tier 2 — Web Search (optional)
        web_evidence_lines: list[str] = []
        web_citations: list[Citation] = []
        if self._web_search is not None and missing_pairs_t2:
            web_evidence_lines, web_citations = await self._query_web(
                missing_pairs_t2, context.language
            )

        # 5. LLM synthesis — one call in the user's language
        ddimdl_block = "\n".join(h.as_evidence_line() for h in ddimdl_hits) or "(no entries)"
        rag_block = build_chunk_context(rag_en + rag_ar)
        web_block = "\n".join(web_evidence_lines) or "(no web search evidence)"

        synthesised, tokens = await self._synthesise(
            drugs=drugs,
            pairs=pairs,
            language=context.language,
            ddimdl_block=ddimdl_block,
            rag_block=rag_block,
            web_block=web_block,
        )

        # 6. Convert LLM output to InteractionPair list
        bilingual_pairs = self._to_interaction_pairs(synthesised.pairs, context.language)
        overall = self._compute_overall_severity(bilingual_pairs)

        data = InteractionsData(pairs=bilingual_pairs, overall_severity=overall)

        # 7. Citations: DDIMDL source files + retrieved chunks + web URLs
        citations = self._build_citations(ddimdl_hits, rag_en + rag_ar, web_citations)
        confidence = self._compute_confidence(
            n_total=len(pairs),
            n_ddimdl=len(ddimdl_covered),
            n_rag=len(rag_covered),
            n_web=len(missing_pairs_t2)
            - sum(1 for _ in missing_pairs_t2 if self._web_search is None),
        )

        return AgentRunResult(
            data=data,
            citations=citations,
            confidence=confidence,
            tokens_used=tokens,
        )

    # ─── Step implementations ─────────────────────────────────────

    async def _normalise_all(self, identifiers: list[DrugIdentifier]) -> list[NormalisedDrug]:
        async def _one(identifier: DrugIdentifier) -> NormalisedDrug:
            ref = identifier.name or identifier.rxcui
            if not ref:
                raise DrugNotFoundException("DrugIdentifier requires either name or rxcui")
            return await self._normaliser.resolve(ref)

        return await asyncio.gather(*[_one(d) for d in identifiers])

    @staticmethod
    def _pair_key(a: str, b: str) -> tuple[str, str]:
        return tuple(sorted([a.lower(), b.lower()]))  # type: ignore[return-value]

    async def _query_ddimdl(
        self, pairs: list[tuple[NormalisedDrug, NormalisedDrug]]
    ) -> list[_DDIMDLHit]:
        if not pairs:
            return []
        # Late import — keeps this module standalone-importable.
        from data_pipeline.ingestion.ddimdl_postgres_ingester import DDIMDLInteraction

        conditions = []
        for a, b in pairs:
            an, bn = a.generic_name, b.generic_name
            conditions.append(
                or_(
                    and_(DDIMDLInteraction.drug_a == an, DDIMDLInteraction.drug_b == bn),
                    and_(DDIMDLInteraction.drug_a == bn, DDIMDLInteraction.drug_b == an),
                )
            )
        stmt = select(DDIMDLInteraction).where(or_(*conditions))

        async with self._ddimdl_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()

        return [
            _DDIMDLHit(
                drug_a=row.drug_a,
                drug_b=row.drug_b,
                interaction_text=row.interaction_text,
                severity_code=row.severity_code,
                source_file=row.source_file,
            )
            for row in rows
        ]

    async def _query_drug_rag(
        self, pairs: list[tuple[NormalisedDrug, NormalisedDrug]]
    ) -> tuple[list[RetrievedChunk], list[RetrievedChunk]]:
        if not pairs:
            return [], []
        # One combined natural-language query covering all pairs:
        # the LLM is good at picking out the pair-specific info from
        # a broad retrieval; cheaper than N parallel searches.
        query = " ; ".join(f"{a.generic_name} {b.generic_name} interaction" for a, b in pairs)
        en_chunks, ar_chunks = await asyncio.gather(
            self._en_retriever.search(query, top_k=self._top_k),
            self._ar_retriever.search(query, top_k=self._top_k),
        )
        return en_chunks, ar_chunks

    def _pairs_covered_by_chunks(
        self,
        pairs: list[tuple[NormalisedDrug, NormalisedDrug]],
        chunks: list[RetrievedChunk],
    ) -> set[tuple[str, str]]:
        """Best-effort: a pair is "covered" if both drug names appear in any chunk."""
        covered: set[tuple[str, str]] = set()
        for a, b in pairs:
            an_l = a.generic_name.lower()
            bn_l = b.generic_name.lower()
            for c in chunks:
                t = c.text.lower()
                if an_l in t and bn_l in t:
                    covered.add(self._pair_key(a.generic_name, b.generic_name))
                    break
        return covered

    async def _query_web(
        self,
        pairs: list[tuple[NormalisedDrug, NormalisedDrug]],
        language: Language,
    ) -> tuple[list[str], list[Citation]]:
        if self._web_search is None:
            return [], []
        lines: list[str] = []
        citations: list[Citation] = []
        for a, b in pairs:
            try:
                result = await self._web_search.find_interaction(
                    a.generic_name, b.generic_name, language
                )
            except Exception as exc:
                _log.warning(
                    "agent.interaction.web_search_failed",
                    drug_a=a.generic_name,
                    drug_b=b.generic_name,
                    error=str(exc),
                )
                continue
            if result is None:
                continue
            description, url = result
            lines.append(f"- {a.generic_name} ↔ {b.generic_name}: {description} (source: {url})")
            citations.append(
                Citation(
                    source="web_search",
                    title=f"{a.generic_name} + {b.generic_name}",
                    url=url,
                    snippet=description[:200],
                )
            )
        return lines, citations

    async def _synthesise(
        self,
        *,
        drugs: list[NormalisedDrug],
        pairs: list[tuple[NormalisedDrug, NormalisedDrug]],
        language: Language,
        ddimdl_block: str,
        rag_block: str,
        web_block: str,
    ) -> tuple[_LLMInteractionsResponse, int]:
        template = load_prompt(self._prompts_dir, "interactions", language)
        pairs_listing = "\n".join(f"- {a.generic_name} + {b.generic_name}" for a, b in pairs)
        user_prompt = format_prompt(
            template,
            drug_pairs=pairs_listing,
            ddimdl_evidence=ddimdl_block,
            rag_evidence=rag_block,
            web_evidence=web_block,
        )
        system = (
            "You return ONLY a JSON object matching the requested schema. No prose, no markdown."
            if language == "en"
            else "أنت تنتج فقط كائن JSON يطابق المخطط المطلوب. بدون نثر، بدون markdown."
        )
        return await synthesise_json(
            llm_client=self._llm,
            model=self._model,
            system_prompt=system,
            user_prompt=user_prompt,
            schema=_LLMInteractionsResponse,
            max_tokens=1200,
        )

    def _to_interaction_pairs(
        self, llm_pairs: list[_LLMInteractionPair], language: Language
    ) -> list[InteractionPair]:
        out: list[InteractionPair] = []
        for p in llm_pairs:
            # Description comes back in the user's language; mirror to
            # both BilingualText fields so consumers always have the
            # user's language populated. The bilingual orchestrator
            # (commit 12) can later enrich with the other-language
            # description by running the agent twice.
            desc = (
                BilingualText(en=p.description, ar=p.description)
                if language == "en"
                else BilingualText(en=p.description, ar=p.description)
            )
            # Validate severity / source_tier defensively
            severity: Severity = p.severity if p.severity in SEVERITY_ORDER else "minor"
            source_tier = (
                p.source_tier
                if p.source_tier in {"ddimdl", "drug_rag", "web_search"}
                else "drug_rag"
            )
            out.append(
                InteractionPair(
                    drug_a=p.drug_a,
                    drug_b=p.drug_b,
                    severity=severity,
                    description=desc,
                    source_tier=source_tier,  # type: ignore[arg-type]
                )
            )
        return out

    def _compute_overall_severity(self, pairs: list[InteractionPair]) -> Severity | None:
        if not pairs:
            return None
        return max(pairs, key=lambda p: SEVERITY_ORDER[p.severity]).severity

    def _build_citations(
        self,
        ddimdl_hits: list[_DDIMDLHit],
        rag_chunks: list[RetrievedChunk],
        web_citations: list[Citation],
    ) -> list[Citation]:
        citations: list[Citation] = []
        for hit in ddimdl_hits:
            citations.append(
                Citation(
                    source="ddimdl",
                    title=f"{hit.drug_a} + {hit.drug_b}",
                    url=None,
                    snippet=hit.interaction_text[:200] if hit.interaction_text else None,
                )
            )
        seen: set[tuple[str, int]] = set()
        for chunk in rag_chunks:
            key = (chunk.sha256, chunk.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            citations.append(chunk.to_citation())
        citations.extend(web_citations)
        return citations

    def _compute_confidence(self, *, n_total: int, n_ddimdl: int, n_rag: int, n_web: int) -> float:
        if n_total == 0:
            return 0.0
        # Weight tiers — DDIMDL is authoritative, RAG is good, web is best-effort.
        covered_score = (n_ddimdl * 1.0 + n_rag * 0.85 + n_web * 0.7) / n_total
        return max(0.3, min(1.0, covered_score))


__all__ = ["InteractionAgent", "WebSearchAgentLike"]
