"""Drug RAG retrieval helper.

Searches the per-language Qdrant collections (``drugs_en`` /
``drugs_ar``) populated by ``data-pipeline/ingestion/drug_rag_ingester.py``
during PR1.

Public surface:

* ``RetrievedChunk`` — one search hit with text + score + payload.
* ``DrugRAGRetriever`` — wraps a Qdrant client + an Embedder for the
  target language; exposes ``search(query, top_k)``.

Two retrievers (en + ar) are constructed at agent init time. The
agent fans out queries to both in parallel via ``asyncio.gather``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from services.drug_service.exceptions import DrugRAGException
from services.drug_service.models.schemas import Citation, Language
from shared.embedding import Embedder
from shared.logger import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    score: float
    source_pdf: str
    sha256: str
    chunk_index: int
    language: Language
    extra: dict[str, Any]

    def to_citation(self) -> Citation:
        # Use the first 200 chars as the snippet — enough for the
        # frontend's hover-preview, not enough to expose copyrighted
        # bulk material.
        snippet = self.text[:200] + ("…" if len(self.text) > 200 else "")
        return Citation(
            source="drug_rag",
            title=self.source_pdf.rsplit("/", 1)[-1],
            url=None,
            chunk_id=f"{self.sha256}:{self.chunk_index}",
            snippet=snippet,
        )


class QdrantClientLike(Protocol):
    """Subset of qdrant_client.AsyncQdrantClient we use."""

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        with_payload: bool = True,
    ) -> list[Any]: ...


class DrugRAGRetriever:
    """Single-language search against one Qdrant collection."""

    def __init__(
        self,
        *,
        qdrant_client: QdrantClientLike,
        embedder: Embedder,
        collection_name: str,
        language: Language,
    ) -> None:
        self._qdrant = qdrant_client
        self._embedder = embedder
        self._collection = collection_name
        self._language = language

    @property
    def language(self) -> Language:
        return self._language

    async def search(self, query: str, *, top_k: int = 5) -> list[RetrievedChunk]:
        try:
            [vector] = await self._embedder.embed([query])
        except Exception as exc:
            _log.warning("drug_rag.embed_failed", language=self._language, error=str(exc))
            raise DrugRAGException(f"Embedding failed: {exc}") from exc

        try:
            hits = await self._qdrant.search(
                collection_name=self._collection,
                query_vector=vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            _log.warning(
                "drug_rag.search_failed",
                collection=self._collection,
                error=str(exc),
            )
            raise DrugRAGException(f"Qdrant search failed: {exc}") from exc

        chunks: list[RetrievedChunk] = []
        for hit in hits:
            payload = _payload_of(hit)
            text = payload.get("text", "")
            if not text:
                continue
            chunks.append(
                RetrievedChunk(
                    text=text,
                    score=_score_of(hit),
                    source_pdf=payload.get("source_pdf", "unknown"),
                    sha256=payload.get("sha256", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    language=self._language,
                    extra={k: v for k, v in payload.items() if k not in {"text"}},
                )
            )
        return chunks


def _payload_of(hit: Any) -> dict[str, Any]:
    """Extract payload from a qdrant search hit, tolerating client versions."""
    payload = getattr(hit, "payload", None)
    if isinstance(payload, dict):
        return payload
    # Newer qdrant clients may dict-ify themselves
    if isinstance(hit, dict):
        return hit.get("payload") or {}
    return {}


def _score_of(hit: Any) -> float:
    score = getattr(hit, "score", None)
    if score is not None:
        return float(score)
    if isinstance(hit, dict):
        return float(hit.get("score", 0.0))
    return 0.0


def build_chunk_context(chunks: list[RetrievedChunk]) -> str:
    """Format a list of chunks as a prompt context block.

    Each chunk is numbered so the LLM can cite back ``[1]``, ``[2]``
    in its response. Source PDF is shown so the model knows what kind
    of authority each chunk has.
    """
    if not chunks:
        return "(no relevant retrieved content)"
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        source = c.source_pdf.rsplit("/", 1)[-1]
        lines.append(f"[{i}] (source: {source}, score: {c.score:.2f})\n{c.text}")
    return "\n\n".join(lines)


__all__ = [
    "DrugRAGRetriever",
    "QdrantClientLike",
    "RetrievedChunk",
    "build_chunk_context",
]
