"""Tests for the drug-RAG ingester.

Uses a fake Storage, fake Qdrant, and an injected PDF extractor so
the tests do not require pdfplumber, GCS, or a real Qdrant instance.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from data_pipeline.ingestion.drug_rag_ingester import (  # type: ignore[import-not-found]
    Base,
    DrugRAGIngester,
    DrugRAGIngestionMarker,
)
from shared.embedding import BilingualEmbedder, FakeEmbedder

# ─── Fakes ────────────────────────────────────────────────────────


@dataclass
class FakeBlob:
    path: str


class FakeStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.writes: dict[str, bytes] = {}

    async def list_prefix(self, prefix: str) -> AsyncIterator[FakeBlob]:
        for path in sorted(self.files):
            if path.startswith(prefix):
                yield FakeBlob(path=path)

    async def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_bytes(self, path: str, data: bytes) -> None:
        self.writes[path] = data


class FakeQdrant:
    """Mimics qdrant_client.AsyncQdrantClient minimally."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.points: dict[str, list[Any]] = {}

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    async def create_collection(self, collection_name: str, vectors_config: Any) -> Any:
        self.collections[collection_name] = {"vectors_config": vectors_config}
        self.points.setdefault(collection_name, [])

    async def upsert(self, collection_name: str, points: list[Any]) -> Any:
        self.points.setdefault(collection_name, []).extend(points)

    async def delete(self, collection_name: str, points_selector: Any) -> Any:
        pass


def fake_pdf_extractor(_pdf_bytes: bytes) -> list[tuple[int, str]]:
    """Yields one synthetic English page + one Arabic page."""
    en = (
        "Ibuprofen is a non-steroidal anti-inflammatory drug used for pain relief. "
        "It works by inhibiting cyclooxygenase enzymes. Common side effects include "
        "gastrointestinal upset and headache. The recommended dose for adults is "
        "200-400 mg every four to six hours as needed."
    )
    ar = (
        "الإيبوبروفين دواء مضاد للالتهاب غير ستيرويدي يستخدم لتخفيف الألم. "
        "يعمل عن طريق تثبيط إنزيمات الأكسدة الحلقية. تشمل الآثار الجانبية الشائعة "
        "اضطراب المعدة والصداع. الجرعة الموصى بها للبالغين هي 200-400 ملغ كل أربع إلى ست ساعات."
    )
    return [(1, en), (2, ar)]


# Patch the TextChunker to NOT depend on tiktoken / nltk, since this is
# the data-pipeline test layer not the chunker test layer.
class StubChunker:
    """Tiny chunker that emits one chunk per input call."""

    def chunk(self, text: str, *, source: str, metadata: dict[str, Any] | None = None) -> list[Any]:
        from shared.chunking import TextChunk

        if not text.strip():
            return []
        return [
            TextChunk(
                text=text,
                token_count=len(text) // 4,
                chunk_index=0,
                source=source,
                metadata=dict(metadata or {}),
            )
        ]


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def embedder() -> BilingualEmbedder:
    return BilingualEmbedder(
        en_embedder=FakeEmbedder(dimension=8, model_name="fake-en"),
        ar_embedder=FakeEmbedder(dimension=16, model_name="fake-ar"),
    )


@pytest.fixture
def patched_collections(monkeypatch: pytest.MonkeyPatch):
    """Stub out qdrant_client.models access in _ensure_collections + _upsert."""

    class FakeVectorParams:
        def __init__(self, size: int, distance: Any) -> None:
            self.size = size
            self.distance = distance

    class FakeDistance:
        COSINE = "cosine"

    class FakePointStruct:
        def __init__(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload

    fake_models = type(
        "QM",
        (),
        {
            "VectorParams": FakeVectorParams,
            "Distance": FakeDistance,
            "PointStruct": FakePointStruct,
        },
    )()

    import sys as _sys

    fake_module = type(_sys)("qdrant_client")
    fake_module.models = fake_models  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "qdrant_client", fake_module)
    return fake_models


# ─── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creates_both_collections_on_first_run(
    session_factory, embedder, patched_collections
) -> None:
    storage = FakeStorage(
        {
            "gs://b/raw/drugs_com/general_pdfs/ibuprofen.pdf": b"%PDF-fake-1",
        }
    )
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    assert "drugs_en" in qdrant.collections
    assert "drugs_ar" in qdrant.collections
    assert qdrant.collections["drugs_en"]["vectors_config"].size == 8
    assert qdrant.collections["drugs_ar"]["vectors_config"].size == 16


@pytest.mark.asyncio
async def test_routes_chunks_to_correct_collection(
    session_factory, embedder, patched_collections
) -> None:
    storage = FakeStorage({"gs://b/raw/drugs_com/x.pdf": b"%PDF-fake"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    result = await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    assert result.pdfs_processed == 1
    assert result.total_chunks_en == 1
    assert result.total_chunks_ar == 1
    # English chunk went to drugs_en, Arabic chunk to drugs_ar
    assert len(qdrant.points["drugs_en"]) == 1
    assert len(qdrant.points["drugs_ar"]) == 1
    assert qdrant.points["drugs_en"][0].payload["language"] == "en"
    assert qdrant.points["drugs_ar"][0].payload["language"] == "ar"


@pytest.mark.asyncio
async def test_rerun_with_unchanged_pdf_skips(
    session_factory, embedder, patched_collections
) -> None:
    storage = FakeStorage({"gs://b/raw/drugs_com/x.pdf": b"%PDF-fake"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    second = await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    assert second.pdfs_skipped == 1
    assert second.pdfs_processed == 0


@pytest.mark.asyncio
async def test_force_reprocesses_unchanged_pdf(
    session_factory, embedder, patched_collections
) -> None:
    storage = FakeStorage({"gs://b/raw/drugs_com/x.pdf": b"%PDF-fake"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    second = await ingester.ingest(prefix="gs://b/raw/drugs_com/", force=True)
    assert second.pdfs_processed == 1
    assert second.pdfs_skipped == 0


@pytest.mark.asyncio
async def test_changed_pdf_triggers_reprocess(
    session_factory, embedder, patched_collections
) -> None:
    storage = FakeStorage({"gs://b/raw/drugs_com/x.pdf": b"%PDF-v1"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    # PDF replaced upstream
    storage.files["gs://b/raw/drugs_com/x.pdf"] = b"%PDF-v2-different"
    second = await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    assert second.pdfs_processed == 1


@pytest.mark.asyncio
async def test_marker_records_per_language_counts(
    session_factory, embedder, patched_collections
) -> None:
    storage = FakeStorage({"gs://b/raw/drugs_com/x.pdf": b"%PDF-fake"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    async with session_factory() as session:
        markers = (await session.execute(select(DrugRAGIngestionMarker))).scalars().all()
        assert len(markers) == 1
        m = markers[0]
        assert m.source_pdf == "gs://b/raw/drugs_com/x.pdf"
        assert m.chunk_count == 2
        assert m.en_chunks == 1
        assert m.ar_chunks == 1


@pytest.mark.asyncio
async def test_manifest_written(session_factory, embedder, patched_collections) -> None:
    storage = FakeStorage({"gs://b/raw/drugs_com/x.pdf": b"%PDF-fake"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    await ingester.ingest(prefix="gs://b/raw/drugs_com/", manifest_uri="gs://b/manifests/drug_rag/")
    manifest_keys = [k for k in storage.writes if k.startswith("gs://b/manifests/drug_rag/")]
    assert len(manifest_keys) == 1
    import json as _json

    manifest = _json.loads(storage.writes[manifest_keys[0]])
    assert manifest["ingester"] == "drug_rag"
    assert manifest["pdfs_processed"] == 1


@pytest.mark.asyncio
async def test_only_pdf_files_listed(session_factory, embedder, patched_collections) -> None:
    """Non-PDF files in the prefix should be ignored."""
    storage = FakeStorage(
        {
            "gs://b/raw/drugs_com/x.pdf": b"%PDF-fake",
            "gs://b/raw/drugs_com/readme.txt": b"this is not a pdf",
        }
    )
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=fake_pdf_extractor,
    )
    result = await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    assert result.pdfs_processed == 1


@pytest.mark.asyncio
async def test_pdf_with_extraction_failure_records_error(
    session_factory, embedder, patched_collections
) -> None:
    def bad_extractor(_b: bytes) -> list[tuple[int, str]]:
        raise RuntimeError("pdfplumber boom")

    storage = FakeStorage({"gs://b/raw/drugs_com/bad.pdf": b"%PDF-broken"})
    qdrant = FakeQdrant()
    ingester = DrugRAGIngester(
        storage_client=storage,
        qdrant_client=qdrant,
        session_factory=session_factory,
        embedder=embedder,
        chunker=StubChunker(),  # type: ignore[arg-type]
        pdf_extractor=bad_extractor,
    )
    result = await ingester.ingest(prefix="gs://b/raw/drugs_com/")
    assert result.pdfs_failed == 1
    assert result.pdf_results[0].error is not None
    assert "pdfplumber boom" in result.pdf_results[0].error
