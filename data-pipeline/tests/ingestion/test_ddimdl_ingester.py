"""Tests for the DDIMDL Postgres ingester.

Uses in-memory SQLite via aiosqlite + a fake storage client so we
don't need real Postgres or GCS access. The ingester runs in
``dialect="sqlite"`` mode which uses portable de-duplication.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make sure shared/* and data_pipeline.* are importable from this test
_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from data_pipeline.ingestion.ddimdl_postgres_ingester import (  # type: ignore[import-not-found]
    Base,
    DDIMDLDrug,
    DDIMDLIngester,
    DDIMDLInteraction,
    DDIMDLIngestionMarker,
    DDIMDLSeverityCode,
    parse_drugs_csv,
    parse_interactions_csv,
    parse_severity_csv,
)

DRUGS_CSV = b"""drugbank_id,drug_name,molecular_weight,target
DB001,Aspirin,180.16,COX
DB002,Ibuprofen,206.28,COX
DB003,Warfarin,308.33,VKORC1
"""

INTERACTIONS_CSV = b"""drug_a,drug_b,interaction_text,severity
Aspirin,Warfarin,Increased bleeding risk,major
Ibuprofen,Warfarin,Increased bleeding risk,major
Aspirin,Ibuprofen,Reduced cardioprotective effect,moderate
"""

SEVERITY_CSV = b"""code,label,description
contraindicated,Contraindicated,Do not co-administer
major,Major,Avoid combination if possible
moderate,Moderate,Monitor closely
minor,Minor,Minimal clinical significance
"""


class FakeStorage:
    """In-memory storage client mirroring shared.storage.StorageClient surface."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.writes: dict[str, bytes] = {}

    async def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_bytes(self, path: str, data: bytes) -> None:
        self.writes[path] = data


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


# ─── parsers ───────────────────────────────────────────────────────


def test_parse_drugs_csv_extracts_required_columns() -> None:
    rows = parse_drugs_csv(DRUGS_CSV)
    assert len(rows) == 3
    assert rows[0]["drugbank_id"] == "DB001"
    assert rows[0]["drug_name"] == "Aspirin"
    assert rows[0]["raw_features"] == {"molecular_weight": "180.16", "target": "COX"}


def test_parse_drugs_csv_tolerates_column_name_variants() -> None:
    rows = parse_drugs_csv(b"id,name\nDB001,Aspirin\n")
    assert rows == [{"drugbank_id": "DB001", "drug_name": "Aspirin", "raw_features": None}]


def test_parse_interactions_csv() -> None:
    rows = parse_interactions_csv(INTERACTIONS_CSV, source_file="gs://x", source_sha256="abc")
    assert len(rows) == 3
    assert rows[0]["drug_a"] == "Aspirin"
    assert rows[0]["drug_b"] == "Warfarin"
    assert rows[0]["severity_code"] == "major"
    assert rows[0]["source_file"] == "gs://x"


def test_parse_severity_csv() -> None:
    rows = parse_severity_csv(SEVERITY_CSV)
    codes = {r["code"] for r in rows}
    assert codes == {"contraindicated", "major", "moderate", "minor"}


# ─── full ingestion flow ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_ingest_populates_all_tables(session_factory) -> None:
    storage = FakeStorage(
        {
            "gs://b/drugs.csv": DRUGS_CSV,
            "gs://b/interactions.csv": INTERACTIONS_CSV,
            "gs://b/severity.csv": SEVERITY_CSV,
        }
    )
    ingester = DDIMDLIngester(
        storage_client=storage,
        session_factory=session_factory,
        dialect="sqlite",
        batch_size=10,
    )
    result = await ingester.ingest(
        drugs_uri="gs://b/drugs.csv",
        interactions_uri="gs://b/interactions.csv",
        severity_uri="gs://b/severity.csv",
        manifest_uri="gs://b/manifests/",
    )
    assert result.drugs_inserted == 3
    assert result.severity_inserted == 4
    assert result.interactions_inserted == 3

    async with session_factory() as session:
        drugs = (await session.execute(select(DDIMDLDrug))).scalars().all()
        assert len(drugs) == 3
        interactions = (await session.execute(select(DDIMDLInteraction))).scalars().all()
        assert len(interactions) == 3

    # Manifest written
    assert any(path.startswith("gs://b/manifests/ddimdl_") for path in storage.writes)


@pytest.mark.asyncio
async def test_rerun_with_unchanged_files_is_skipped(session_factory) -> None:
    storage = FakeStorage(
        {
            "gs://b/drugs.csv": DRUGS_CSV,
            "gs://b/interactions.csv": INTERACTIONS_CSV,
            "gs://b/severity.csv": SEVERITY_CSV,
        }
    )
    ingester = DDIMDLIngester(
        storage_client=storage,
        session_factory=session_factory,
        dialect="sqlite",
    )

    # First run loads everything
    first = await ingester.ingest(
        drugs_uri="gs://b/drugs.csv",
        interactions_uri="gs://b/interactions.csv",
        severity_uri="gs://b/severity.csv",
    )
    assert first.drugs_inserted == 3

    # Second run sees matching SHA-256 markers and skips
    second = await ingester.ingest(
        drugs_uri="gs://b/drugs.csv",
        interactions_uri="gs://b/interactions.csv",
        severity_uri="gs://b/severity.csv",
    )
    assert second.drugs_skipped_marker is True
    assert second.interactions_skipped_marker is True
    assert second.severity_skipped_marker is True
    assert second.drugs_inserted == 0


@pytest.mark.asyncio
async def test_force_flag_re_ingests(session_factory) -> None:
    storage = FakeStorage(
        {
            "gs://b/drugs.csv": DRUGS_CSV,
            "gs://b/interactions.csv": INTERACTIONS_CSV,
        }
    )
    ingester = DDIMDLIngester(
        storage_client=storage, session_factory=session_factory, dialect="sqlite"
    )
    await ingester.ingest(drugs_uri="gs://b/drugs.csv", interactions_uri="gs://b/interactions.csv")
    # force=True bypasses the marker check
    second = await ingester.ingest(
        drugs_uri="gs://b/drugs.csv",
        interactions_uri="gs://b/interactions.csv",
        force=True,
    )
    assert second.drugs_skipped_marker is False
    # drugs_inserted reports how many rows the parser produced; the
    # ON CONFLICT path on PG would track real inserts. For sqlite,
    # second-run inserts are 0 because of the existing PK rows.
    assert second.drugs_inserted == 3  # rows attempted
    # Interactions: all duplicates this time
    assert second.interactions_inserted == 0


@pytest.mark.asyncio
async def test_marker_updated_on_successful_ingest(session_factory) -> None:
    storage = FakeStorage(
        {"gs://b/drugs.csv": DRUGS_CSV, "gs://b/interactions.csv": INTERACTIONS_CSV}
    )
    ingester = DDIMDLIngester(
        storage_client=storage, session_factory=session_factory, dialect="sqlite"
    )
    await ingester.ingest(drugs_uri="gs://b/drugs.csv", interactions_uri="gs://b/interactions.csv")
    async with session_factory() as session:
        marker = await session.get(DDIMDLIngestionMarker, "gs://b/drugs.csv")
        assert marker is not None
        assert len(marker.source_sha256) == 64  # SHA-256 hex


@pytest.mark.asyncio
async def test_changed_file_triggers_reingest(session_factory) -> None:
    storage = FakeStorage(
        {"gs://b/drugs.csv": DRUGS_CSV, "gs://b/interactions.csv": INTERACTIONS_CSV}
    )
    ingester = DDIMDLIngester(
        storage_client=storage, session_factory=session_factory, dialect="sqlite"
    )
    await ingester.ingest(drugs_uri="gs://b/drugs.csv", interactions_uri="gs://b/interactions.csv")

    # Simulate the CSV being updated upstream with a new row
    storage.files["gs://b/drugs.csv"] = DRUGS_CSV + b"DB004,Acetaminophen,151.16,COX\n"

    second = await ingester.ingest(
        drugs_uri="gs://b/drugs.csv", interactions_uri="gs://b/interactions.csv"
    )
    assert second.drugs_skipped_marker is False  # SHA changed → re-processed

    async with session_factory() as session:
        drugs = (await session.execute(select(DDIMDLDrug))).scalars().all()
        assert len(drugs) == 4  # new drug now present
        assert any(d.drug_name == "Acetaminophen" for d in drugs)


@pytest.mark.asyncio
async def test_severity_optional(session_factory) -> None:
    storage = FakeStorage(
        {"gs://b/drugs.csv": DRUGS_CSV, "gs://b/interactions.csv": INTERACTIONS_CSV}
    )
    ingester = DDIMDLIngester(
        storage_client=storage, session_factory=session_factory, dialect="sqlite"
    )
    result = await ingester.ingest(
        drugs_uri="gs://b/drugs.csv",
        interactions_uri="gs://b/interactions.csv",
        severity_uri=None,
    )
    assert result.severity_inserted == 0
    async with session_factory() as session:
        codes = (await session.execute(select(DDIMDLSeverityCode))).scalars().all()
        assert codes == []
