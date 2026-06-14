"""DDIMDL CSV → Postgres ingester.

Reads three DDIMDL CSVs from cloud storage and loads them into Postgres
tables owned by drug-service:

* ``ddimdl_drugs`` — one row per molecular drug profile (DrugBank 5.1.3).
* ``ddimdl_interactions`` — one row per drug-drug interaction pair,
  unique by ``(drug_a, drug_b)``. Idempotent: re-runs skip pairs that
  are already present via ``INSERT ... ON CONFLICT DO NOTHING``.
* ``ddimdl_severity_codes`` — lookup table of severity codes used by
  the interactions table.

Per-file idempotency is enforced by ``ddimdl_ingestion_markers``: each
input CSV's SHA-256 is recorded after a successful run; subsequent
runs skip the file unless ``--force`` is passed.

After a run, a JSON manifest is uploaded to the storage URI given by
``--manifest-uri`` (default ``gs://maisys-data-dev/manifests/ddimdl/``).

Progress events stream to the Redis channel ``progress:ingestion.ddimdl``
per the data-pipeline ingester contract.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared.logger import get_logger
from shared.progress import ProgressEvent, ProgressPublisher

_log = get_logger(__name__)

PROGRESS_CHANNEL_JOB_ID = "ingestion.ddimdl"
DEFAULT_MANIFEST_URI = "gs://maisys-data-dev/manifests/ddimdl/"
DEFAULT_BATCH_SIZE = 1000


# ─── ORM ──────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Local declarative base for DDIMDL tables.

    Kept separate from ``shared.models.Base`` to keep the migration
    surface scoped to data-pipeline. Production migrations live under
    ``data-pipeline/ingestion/migrations/ddimdl/``.
    """


class DDIMDLDrug(Base):
    __tablename__ = "ddimdl_drugs"
    drugbank_id: Mapped[str] = mapped_column(String, primary_key=True)
    drug_name: Mapped[str] = mapped_column(String, nullable=False)
    raw_features: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DDIMDLSeverityCode(Base):
    __tablename__ = "ddimdl_severity_codes"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class DDIMDLInteraction(Base):
    __tablename__ = "ddimdl_interactions"
    __table_args__ = (UniqueConstraint("drug_a", "drug_b", name="uq_ddimdl_pair"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drug_a: Mapped[str] = mapped_column(String, nullable=False, index=True)
    drug_b: Mapped[str] = mapped_column(String, nullable=False, index=True)
    interaction_text: Mapped[str | None] = mapped_column(String, nullable=True)
    severity_code: Mapped[str | None] = mapped_column(
        String, ForeignKey("ddimdl_severity_codes.code"), nullable=True
    )
    source_file: Mapped[str] = mapped_column(String, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String, nullable=False)


class DDIMDLIngestionMarker(Base):
    __tablename__ = "ddimdl_ingestion_markers"
    source_file: Mapped[str] = mapped_column(String, primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ─── CSV parsers (tolerant of column-name variants) ───────────────


def _read_csv_rows(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")  # strip BOM if present
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _pick(row: dict[str, str], *keys: str) -> str | None:
    """Case-insensitive first-hit column getter."""
    lowered = {k.lower(): v for k, v in row.items()}
    for key in keys:
        v = lowered.get(key.lower())
        if v:
            return v
    return None


def parse_drugs_csv(content: bytes) -> list[dict[str, Any]]:
    """Parse the DDIMDL drugs CSV.

    Required columns (case-insensitive): one of {``drugbank_id``,
    ``id``, ``drugbankid``} and one of {``drug_name``, ``name``}.
    Everything else is captured into ``raw_features`` as a JSON dict.
    """
    rows = _read_csv_rows(content)
    parsed: list[dict[str, Any]] = []
    for row in rows:
        drugbank_id = _pick(row, "drugbank_id", "id", "drugbankid")
        drug_name = _pick(row, "drug_name", "name")
        if not drugbank_id or not drug_name:
            continue
        features = {
            k: v
            for k, v in row.items()
            if k.lower() not in {"drugbank_id", "id", "drugbankid", "drug_name", "name"}
        }
        parsed.append(
            {
                "drugbank_id": drugbank_id,
                "drug_name": drug_name,
                "raw_features": features or None,
            }
        )
    return parsed


def parse_interactions_csv(
    content: bytes, *, source_file: str, source_sha256: str
) -> list[dict[str, Any]]:
    """Parse the DDIMDL interactions CSV.

    Required columns: ``drug_a``/``drug_b`` (or ``drug1``/``drug2``).
    Optional: ``interaction_text`` (or ``description``), ``severity``
    (or ``severity_code``).
    """
    rows = _read_csv_rows(content)
    parsed: list[dict[str, Any]] = []
    for row in rows:
        drug_a = _pick(row, "drug_a", "drug1", "drug_1")
        drug_b = _pick(row, "drug_b", "drug2", "drug_2")
        if not drug_a or not drug_b:
            continue
        parsed.append(
            {
                "drug_a": drug_a,
                "drug_b": drug_b,
                "interaction_text": _pick(row, "interaction_text", "description", "text"),
                "severity_code": _pick(row, "severity", "severity_code"),
                "source_file": source_file,
                "source_sha256": source_sha256,
            }
        )
    return parsed


def parse_severity_csv(content: bytes) -> list[dict[str, Any]]:
    """Parse the severity-codes CSV. Required: ``code``, ``label``."""
    rows = _read_csv_rows(content)
    parsed: list[dict[str, Any]] = []
    for row in rows:
        code = _pick(row, "code", "severity_code")
        label = _pick(row, "label", "name")
        if not code or not label:
            continue
        parsed.append(
            {
                "code": code,
                "label": label,
                "description": _pick(row, "description", "notes"),
            }
        )
    return parsed


# ─── Ingester ─────────────────────────────────────────────────────


@dataclass
class IngestionResult:
    drugs_inserted: int = 0
    drugs_skipped_marker: bool = False
    severity_inserted: int = 0
    severity_skipped_marker: bool = False
    interactions_inserted: int = 0
    interactions_skipped_existing: int = 0
    interactions_skipped_marker: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def to_manifest(self) -> dict[str, Any]:
        return {
            "ingester": "ddimdl_postgres",
            "started_at": self.started_at.isoformat(),
            "completed_at": (self.completed_at or datetime.now(timezone.utc)).isoformat(),
            "drugs_inserted": self.drugs_inserted,
            "drugs_skipped_marker": self.drugs_skipped_marker,
            "severity_inserted": self.severity_inserted,
            "severity_skipped_marker": self.severity_skipped_marker,
            "interactions_inserted": self.interactions_inserted,
            "interactions_skipped_existing": self.interactions_skipped_existing,
            "interactions_skipped_marker": self.interactions_skipped_marker,
        }


class StorageClientLike(Protocol):
    """Structural protocol — what we need from shared.storage.StorageClient."""

    async def read_bytes(self, path: str) -> bytes: ...
    async def write_bytes(self, path: str, data: bytes) -> None: ...


class DDIMDLIngester:
    """Loads DDIMDL CSVs into Postgres with per-file idempotency."""

    def __init__(
        self,
        *,
        storage_client: StorageClientLike,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: ProgressPublisher | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dialect: str = "postgresql",
    ) -> None:
        self._storage = storage_client
        self._session_factory = session_factory
        self._publisher = publisher
        self._batch_size = batch_size
        self._dialect = dialect

    async def ingest(
        self,
        *,
        drugs_uri: str,
        interactions_uri: str,
        severity_uri: str | None = None,
        force: bool = False,
        manifest_uri: str = DEFAULT_MANIFEST_URI,
    ) -> IngestionResult:
        result = IngestionResult()
        await self._publish("started", "DDIMDL ingestion starting", 0.0)

        # 1. Severity codes (FK target — must land first)
        if severity_uri is not None:
            await self._publish("in_progress", "Loading severity codes", 5.0)
            count, skipped = await self._ingest_one(
                severity_uri, "severity", force, parser=parse_severity_csv
            )
            result.severity_inserted = count
            result.severity_skipped_marker = skipped

        # 2. Drugs
        await self._publish("in_progress", "Loading drugs", 30.0)
        count, skipped = await self._ingest_one(drugs_uri, "drugs", force, parser=parse_drugs_csv)
        result.drugs_inserted = count
        result.drugs_skipped_marker = skipped

        # 3. Interactions (UPSERT, may have duplicates within file or against prior runs)
        await self._publish("in_progress", "Loading interactions", 60.0)
        inserted, skipped, skipped_existing = await self._ingest_interactions(
            interactions_uri, force
        )
        result.interactions_inserted = inserted
        result.interactions_skipped_existing = skipped_existing
        result.interactions_skipped_marker = skipped

        # 4. Manifest
        await self._publish("in_progress", "Writing manifest", 95.0)
        result.completed_at = datetime.now(timezone.utc)
        manifest_path = (
            manifest_uri.rstrip("/")
            + f"/ddimdl_{result.completed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        await self._storage.write_bytes(
            manifest_path, json.dumps(result.to_manifest(), indent=2).encode("utf-8")
        )

        await self._publish("completed", "DDIMDL ingestion complete", 100.0)
        return result

    async def _ingest_one(
        self,
        uri: str,
        kind: str,
        force: bool,
        *,
        parser: Any,
    ) -> tuple[int, bool]:
        content, sha = await self._read_and_hash(uri)
        async with self._session_factory() as session:
            if not force and await self._marker_matches(session, uri, sha):
                _log.info("ddimdl.skip", uri=uri, sha256=sha[:12])
                return (0, True)
            rows = (
                parser(content)
                if kind != "interactions"
                else parser(content, source_file=uri, source_sha256=sha)
            )
            count = 0
            if kind == "drugs":
                count = await self._upsert_drugs(session, rows)
            elif kind == "severity":
                count = await self._upsert_severity(session, rows)
            await self._set_marker(session, uri, sha, count)
            await session.commit()
        return (count, False)

    async def _ingest_interactions(self, uri: str, force: bool) -> tuple[int, bool, int]:
        content, sha = await self._read_and_hash(uri)
        async with self._session_factory() as session:
            if not force and await self._marker_matches(session, uri, sha):
                _log.info("ddimdl.interactions.skip", uri=uri, sha256=sha[:12])
                return (0, True, 0)
            rows = parse_interactions_csv(content, source_file=uri, source_sha256=sha)
            inserted, skipped_existing = await self._upsert_interactions(session, rows)
            await self._set_marker(session, uri, sha, inserted)
            await session.commit()
        return (inserted, False, skipped_existing)

    async def _read_and_hash(self, uri: str) -> tuple[bytes, str]:
        content = await self._storage.read_bytes(uri)
        sha = hashlib.sha256(content).hexdigest()
        return content, sha

    async def _marker_matches(self, session: AsyncSession, uri: str, sha: str) -> bool:
        marker = await session.get(DDIMDLIngestionMarker, uri)
        return marker is not None and marker.source_sha256 == sha

    async def _set_marker(self, session: AsyncSession, uri: str, sha: str, count: int) -> None:
        marker = await session.get(DDIMDLIngestionMarker, uri)
        if marker is None:
            marker = DDIMDLIngestionMarker(
                source_file=uri,
                source_sha256=sha,
                ingested_at=datetime.now(timezone.utc),
                record_count=count,
            )
            session.add(marker)
        else:
            marker.source_sha256 = sha
            marker.ingested_at = datetime.now(timezone.utc)
            marker.record_count = count

    async def _upsert_drugs(self, session: AsyncSession, rows: list[dict[str, Any]]) -> int:
        total = 0
        for chunk in _batched(rows, self._batch_size):
            if self._dialect == "postgresql":
                stmt = (
                    pg_insert(DDIMDLDrug)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=["drugbank_id"])
                )
                await session.execute(stmt)
            else:
                # SQLite path used by tests: best-effort manual de-dup
                for row in chunk:
                    existing = await session.get(DDIMDLDrug, row["drugbank_id"])
                    if existing is None:
                        session.add(DDIMDLDrug(**row))
            total += len(chunk)
        return total

    async def _upsert_severity(self, session: AsyncSession, rows: list[dict[str, Any]]) -> int:
        total = 0
        for chunk in _batched(rows, self._batch_size):
            if self._dialect == "postgresql":
                stmt = (
                    pg_insert(DDIMDLSeverityCode)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=["code"])
                )
                await session.execute(stmt)
            else:
                for row in chunk:
                    if await session.get(DDIMDLSeverityCode, row["code"]) is None:
                        session.add(DDIMDLSeverityCode(**row))
            total += len(chunk)
        return total

    async def _upsert_interactions(
        self, session: AsyncSession, rows: list[dict[str, Any]]
    ) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        for chunk in _batched(rows, self._batch_size):
            if self._dialect == "postgresql":
                stmt = (
                    pg_insert(DDIMDLInteraction)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=["drug_a", "drug_b"])
                )
                res = await session.execute(stmt)
                # Cast: ON CONFLICT statements always return CursorResult on PG
                cursor_res: CursorResult[Any] = res  # type: ignore[assignment]
                affected = cursor_res.rowcount or 0
                inserted += affected
                skipped += len(chunk) - affected
            else:
                # SQLite path: query existing pairs first
                from sqlalchemy import select

                for row in chunk:
                    q = select(DDIMDLInteraction).where(
                        DDIMDLInteraction.drug_a == row["drug_a"],
                        DDIMDLInteraction.drug_b == row["drug_b"],
                    )
                    if (await session.execute(q)).scalar_one_or_none() is None:
                        session.add(DDIMDLInteraction(**row))
                        inserted += 1
                    else:
                        skipped += 1
        return inserted, skipped

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


def _batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# ─── CLI ──────────────────────────────────────────────────────────


async def _cli(args: argparse.Namespace) -> IngestionResult:
    from shared.storage import StorageClient  # type: ignore[attr-defined]

    engine = create_async_engine(args.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = StorageClient.from_uri(args.drugs_uri)

    publisher: ProgressPublisher | None = None
    if args.redis_url:
        import redis.asyncio as redis_async

        publisher = ProgressPublisher(redis_async.from_url(args.redis_url, decode_responses=True))

    ingester = DDIMDLIngester(
        storage_client=storage,
        session_factory=session_factory,
        publisher=publisher,
        batch_size=args.batch_size,
    )
    try:
        return await ingester.ingest(
            drugs_uri=args.drugs_uri,
            interactions_uri=args.interactions_uri,
            severity_uri=args.severity_uri,
            force=args.force,
            manifest_uri=args.manifest_uri,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="DDIMDL CSV → Postgres ingester")
    parser.add_argument("--drugs-uri", required=True, help="gs:// or s3:// URI to drugs CSV")
    parser.add_argument("--interactions-uri", required=True, help="URI to interactions CSV")
    parser.add_argument("--severity-uri", default=None, help="URI to severity-codes CSV (optional)")
    parser.add_argument(
        "--database-url", default=os.environ.get("DDIMDL_DATABASE_URL"), required=False
    )
    parser.add_argument("--manifest-uri", default=DEFAULT_MANIFEST_URI)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--force", action="store_true", help="Ignore SHA-256 markers and re-ingest")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DDIMDL_DATABASE_URL must be set (or pass --database-url)")
    result = asyncio.run(_cli(args))
    print(json.dumps(result.to_manifest(), indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "Base",
    "DDIMDLDrug",
    "DDIMDLIngestionMarker",
    "DDIMDLIngester",
    "DDIMDLInteraction",
    "DDIMDLSeverityCode",
    "IngestionResult",
    "parse_drugs_csv",
    "parse_interactions_csv",
    "parse_severity_csv",
]
