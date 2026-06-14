"""Drug RAG ingester — PDFs from GCS into bilingual Qdrant collections.

Iterates PDFs under a storage prefix (typically
``gs://maisys-data-dev/raw/drugs_com/``), extracts text via
pdfplumber, chunks via ``shared.chunking.TextChunker``, embeds via
``shared.embedding.BilingualEmbedder``, then upserts the resulting
vectors to two Qdrant collections:

* ``drugs_en`` — English chunks (dimension from the en embedder).
* ``drugs_ar`` — Arabic chunks (dimension from the ar embedder).

CRITICAL: the two collections may have different vector dimensions and
are NOT comparable. Search either one in isolation, then merge by
language at the caller.

Idempotency:

* A Postgres ``drug_rag_ingestion_markers`` table records, per source
  PDF, the SHA-256 of the PDF contents and the count of chunks
  emitted. Re-runs that find a matching marker skip the file.
* ``--force`` bypasses the marker check.

Progress is published to Redis on ``progress:ingestion.drug_rag``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared.chunking import TextChunk, TextChunker
from shared.concurrent import BatchProcessor
from shared.embedding import BilingualEmbedder, EmbeddedItem
from shared.logger import get_logger
from shared.progress import ProgressEvent, ProgressPublisher

_log = get_logger(__name__)

PROGRESS_CHANNEL_JOB_ID = "ingestion.drug_rag"
COLLECTION_EN = "drugs_en"
COLLECTION_AR = "drugs_ar"
DEFAULT_MANIFEST_URI = "gs://maisys-data-dev/manifests/drug_rag/"
DEFAULT_BATCH_SIZE = 10


# ─── ORM (marker table only — chunks live in Qdrant) ──────────────


class Base(DeclarativeBase):
    """Local base for the drug_rag_ingestion_markers table."""


class DrugRAGIngestionMarker(Base):
    __tablename__ = "drug_rag_ingestion_markers"
    source_pdf: Mapped[str] = mapped_column(String, primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    en_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ar_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─── Protocols for injected clients ───────────────────────────────


class StorageClientLike(Protocol):
    """What we need from shared.storage.StorageClient."""

    def list_prefix(self, prefix: str) -> AsyncIterator[Any]: ...
    async def read_bytes(self, path: str) -> bytes: ...
    async def write_bytes(self, path: str, data: bytes) -> None: ...


class QdrantClientLike(Protocol):
    """Subset of qdrant_client.AsyncQdrantClient we use."""

    async def collection_exists(self, collection_name: str) -> bool: ...
    async def create_collection(self, collection_name: str, vectors_config: Any) -> Any: ...
    async def upsert(self, collection_name: str, points: list[Any]) -> Any: ...
    async def delete(self, collection_name: str, points_selector: Any) -> Any: ...


PdfExtractor = Callable[[bytes], list[tuple[int, str]]]
"""Function that turns PDF bytes into ``[(page_number, page_text), ...]``."""


def _default_pdf_extractor(pdf_bytes: bytes) -> list[tuple[int, str]]:
    """Default PDF text extraction via pdfplumber.

    pdfplumber is imported lazily so tests with injected extractors
    don't require the package.
    """
    import pdfplumber

    pages: list[tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((i, text))
    return pages


# ─── Result types ─────────────────────────────────────────────────


@dataclass
class PdfResult:
    """One PDF's outcome (success or failure)."""

    source_pdf: str
    sha256: str | None = None
    chunks_total: int = 0
    chunks_en: int = 0
    chunks_ar: int = 0
    skipped_marker: bool = False
    error: str | None = None


@dataclass
class IngestionResult:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    pdfs_processed: int = 0
    pdfs_skipped: int = 0
    pdfs_failed: int = 0
    total_chunks_en: int = 0
    total_chunks_ar: int = 0
    pdf_results: list[PdfResult] = field(default_factory=list)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "ingester": "drug_rag",
            "started_at": self.started_at.isoformat(),
            "completed_at": (self.completed_at or datetime.now(timezone.utc)).isoformat(),
            "pdfs_processed": self.pdfs_processed,
            "pdfs_skipped": self.pdfs_skipped,
            "pdfs_failed": self.pdfs_failed,
            "total_chunks_en": self.total_chunks_en,
            "total_chunks_ar": self.total_chunks_ar,
            "pdf_results": [
                {
                    "source_pdf": r.source_pdf,
                    "sha256": r.sha256,
                    "chunks_total": r.chunks_total,
                    "chunks_en": r.chunks_en,
                    "chunks_ar": r.chunks_ar,
                    "skipped_marker": r.skipped_marker,
                    "error": r.error,
                }
                for r in self.pdf_results
            ],
        }


# ─── Ingester ─────────────────────────────────────────────────────


class DrugRAGIngester:
    """Per-PDF ingestion pipeline writing to bilingual Qdrant collections."""

    def __init__(
        self,
        *,
        storage_client: StorageClientLike,
        qdrant_client: QdrantClientLike,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: BilingualEmbedder,
        chunker: TextChunker | None = None,
        publisher: ProgressPublisher | None = None,
        pdf_extractor: PdfExtractor | None = None,
        concurrency: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._storage = storage_client
        self._qdrant = qdrant_client
        self._session_factory = session_factory
        self._embedder = embedder
        self._chunker = chunker or TextChunker()
        self._publisher = publisher
        self._pdf_extractor = pdf_extractor or _default_pdf_extractor
        self._concurrency = concurrency

    async def ingest(
        self,
        *,
        prefix: str,
        force: bool = False,
        manifest_uri: str = DEFAULT_MANIFEST_URI,
    ) -> IngestionResult:
        await self._publish("started", f"Drug RAG ingestion: {prefix}", 0.0)

        await self._ensure_collections()

        pdf_paths = await self._list_pdfs(prefix)
        total = len(pdf_paths)
        _log.info("drug_rag.list", prefix=prefix, count=total)

        result = IngestionResult()

        async def _process(path: str) -> PdfResult:
            return await self._process_pdf(path, force=force)

        async def _progress(done: int, total_count: int) -> None:
            pct = (done / max(total_count, 1)) * 95.0
            await self._publish("in_progress", f"{done}/{total_count} PDFs processed", pct)

        processor = BatchProcessor[str, PdfResult](
            _process,
            batch_size=self._concurrency,
            concurrency=self._concurrency,
            on_progress=_progress,
        )
        outcomes = await processor.run(pdf_paths)

        for outcome in outcomes:
            if isinstance(outcome, PdfResult):
                result.pdf_results.append(outcome)
                if outcome.error is not None:
                    result.pdfs_failed += 1
                elif outcome.skipped_marker:
                    result.pdfs_skipped += 1
                else:
                    result.pdfs_processed += 1
                    result.total_chunks_en += outcome.chunks_en
                    result.total_chunks_ar += outcome.chunks_ar
            else:
                # outcome is BaseException — unexpected, since _process catches
                result.pdfs_failed += 1
                result.pdf_results.append(PdfResult(source_pdf="<unknown>", error=str(outcome)))

        result.completed_at = datetime.now(timezone.utc)
        await self._publish("in_progress", "Writing manifest", 98.0)
        manifest_path = (
            manifest_uri.rstrip("/")
            + f"/drug_rag_{result.completed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        await self._storage.write_bytes(
            manifest_path, json.dumps(result.to_manifest(), indent=2).encode("utf-8")
        )

        await self._publish("completed", "Drug RAG ingestion complete", 100.0)
        return result

    async def _process_pdf(self, source_pdf: str, *, force: bool) -> PdfResult:
        try:
            pdf_bytes = await self._storage.read_bytes(source_pdf)
            sha = hashlib.sha256(pdf_bytes).hexdigest()
            outcome = PdfResult(source_pdf=source_pdf, sha256=sha)

            async with self._session_factory() as session:
                if not force and await self._marker_matches(session, source_pdf, sha):
                    outcome.skipped_marker = True
                    return outcome

            # Extract + chunk + embed + upsert
            pages = self._pdf_extractor(pdf_bytes)
            chunks: list[TextChunk] = []
            for page_num, page_text in pages:
                page_chunks = self._chunker.chunk(
                    page_text,
                    source=source_pdf,
                    metadata={"page": page_num, "source_pdf": source_pdf, "sha256": sha},
                )
                chunks.extend(page_chunks)

            if not chunks:
                outcome.chunks_total = 0
            else:
                embedded = await self._embedder.embed([c.text for c in chunks])
                outcome.chunks_total = len(embedded)
                outcome.chunks_en = sum(1 for e in embedded if e.language == "en")
                outcome.chunks_ar = sum(1 for e in embedded if e.language == "ar")
                await self._upsert_to_qdrant(chunks, embedded, source_pdf, sha)

            async with self._session_factory() as session:
                await self._set_marker(
                    session,
                    source_pdf=source_pdf,
                    sha=sha,
                    total=outcome.chunks_total,
                    en=outcome.chunks_en,
                    ar=outcome.chunks_ar,
                )
                await session.commit()

            return outcome
        except Exception as exc:
            _log.warning("drug_rag.pdf.failed", source_pdf=source_pdf, error=str(exc))
            return PdfResult(source_pdf=source_pdf, error=str(exc))

    async def _ensure_collections(self) -> None:
        """Idempotent: create the two collections if they don't exist."""
        from qdrant_client import models as qmodels

        for name, dim in (
            (COLLECTION_EN, self._embedder.en_dimension),
            (COLLECTION_AR, self._embedder.ar_dimension),
        ):
            if not await self._qdrant.collection_exists(name):
                _log.info("drug_rag.collection.create", name=name, dimension=dim)
                await self._qdrant.create_collection(
                    collection_name=name,
                    vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
                )

    async def _list_pdfs(self, prefix: str) -> list[str]:
        paths: list[str] = []
        async for blob in self._storage.list_prefix(prefix):
            path = getattr(blob, "path", str(blob))
            if path.lower().endswith(".pdf"):
                paths.append(path)
        return paths

    async def _marker_matches(self, session: AsyncSession, source_pdf: str, sha: str) -> bool:
        marker = await session.get(DrugRAGIngestionMarker, source_pdf)
        return marker is not None and marker.source_sha256 == sha

    async def _set_marker(
        self,
        session: AsyncSession,
        *,
        source_pdf: str,
        sha: str,
        total: int,
        en: int,
        ar: int,
    ) -> None:
        marker = await session.get(DrugRAGIngestionMarker, source_pdf)
        now = datetime.now(timezone.utc)
        if marker is None:
            session.add(
                DrugRAGIngestionMarker(
                    source_pdf=source_pdf,
                    source_sha256=sha,
                    chunk_count=total,
                    en_chunks=en,
                    ar_chunks=ar,
                    ingested_at=now,
                )
            )
        else:
            marker.source_sha256 = sha
            marker.chunk_count = total
            marker.en_chunks = en
            marker.ar_chunks = ar
            marker.ingested_at = now

    async def _upsert_to_qdrant(
        self,
        chunks: list[TextChunk],
        embedded: list[EmbeddedItem],
        source_pdf: str,
        sha: str,
    ) -> None:
        from qdrant_client import models as qmodels

        en_points: list[Any] = []
        ar_points: list[Any] = []
        for chunk, emb in zip(chunks, embedded):
            point_id = str(uuid.uuid4())
            payload = {
                "text": chunk.text,
                "source_pdf": source_pdf,
                "sha256": sha,
                "token_count": chunk.token_count,
                "chunk_index": chunk.chunk_index,
                "language": emb.language,
                "embedding_model": emb.model_name,
                **chunk.metadata,
            }
            point = qmodels.PointStruct(id=point_id, vector=emb.vector, payload=payload)
            if emb.language == "ar":
                ar_points.append(point)
            else:
                en_points.append(point)

        if en_points:
            await self._qdrant.upsert(collection_name=COLLECTION_EN, points=en_points)
        if ar_points:
            await self._qdrant.upsert(collection_name=COLLECTION_AR, points=ar_points)

    async def _publish(self, status: str, message: str, percent: float) -> None:
        if self._publisher is None:
            return
        await self._publisher.publish(
            ProgressEvent(
                job_id=PROGRESS_CHANNEL_JOB_ID,
                status=status,  # type: ignore[arg-type]
                message=message,
                percent=percent,
            )
        )


# ─── CLI ──────────────────────────────────────────────────────────


async def _cli(args: argparse.Namespace) -> IngestionResult:
    from qdrant_client import AsyncQdrantClient

    from shared.embedding import LiteLLMEmbedder, SentenceTransformerEmbedder
    from shared.storage import StorageClient  # type: ignore[attr-defined]

    engine = create_async_engine(args.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    storage = StorageClient.from_uri(args.prefix)
    qdrant = AsyncQdrantClient(url=args.qdrant_url)
    en_embedder = LiteLLMEmbedder(model=args.en_model)
    ar_embedder = SentenceTransformerEmbedder(model=args.ar_model, dimension=args.ar_dim)
    embedder = BilingualEmbedder(en_embedder=en_embedder, ar_embedder=ar_embedder)

    publisher: ProgressPublisher | None = None
    if args.redis_url:
        import redis.asyncio as redis_async

        publisher = ProgressPublisher(redis_async.from_url(args.redis_url, decode_responses=True))

    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        publisher=publisher,
        concurrency=args.concurrency,
    )
    try:
        return await ingester.ingest(
            prefix=args.prefix, force=args.force, manifest_uri=args.manifest_uri
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Drug RAG ingester (PDFs → Qdrant bilingual)")
    parser.add_argument("--prefix", required=True, help="gs:// or s3:// prefix to scan")
    parser.add_argument("--database-url", default=os.environ.get("DRUG_RAG_DATABASE_URL"))
    parser.add_argument(
        "--qdrant-url", default=os.environ.get("QDRANT_URL", "http://localhost:6333")
    )
    parser.add_argument("--en-model", default="openai/text-embedding-3-small")
    parser.add_argument("--ar-model", default="Omartificial-Intelligence-Space/Arabic-MiniLM-L6-v2")
    parser.add_argument("--ar-dim", type=int, default=384)
    parser.add_argument("--manifest-uri", default=DEFAULT_MANIFEST_URI)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    parser.add_argument("--concurrency", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DRUG_RAG_DATABASE_URL must be set (or pass --database-url)")
    result = asyncio.run(_cli(args))
    print(json.dumps(result.to_manifest(), indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "Base",
    "DrugRAGIngester",
    "DrugRAGIngestionMarker",
    "IngestionResult",
    "PdfExtractor",
    "PdfResult",
    "QdrantClientLike",
    "StorageClientLike",
]
