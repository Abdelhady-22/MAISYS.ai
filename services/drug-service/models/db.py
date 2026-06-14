"""SQLAlchemy ORM tables owned by drug-service.

Three tables today:

* ``rxnorm_cache`` — the local cache of (input_name → rxcui, generic,
  brands, class) populated incrementally as the normaliser resolves
  drugs. Acts as the first-tier exact-match lookup before falling
  back to fuzzy matching or the RxNorm API.
* ``drug_query_log`` — one row per drug-service request for audit and
  per-user rate-limit analysis. Captures correlation_id (==
  request_id) so we can stitch logs across agents.
* ``rxnorm_sync_marker`` — records the SHA-256 of the last raw/rxnorm/
  bulk file ingested. Used by the migration / preload script to skip
  unchanged sources.

The shared ``Base`` from ``shared.models`` is used so a single Alembic
chain covers every service.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.models import Base, TimestampMixin, UUIDMixin


class RxNormCacheEntry(Base, UUIDMixin, TimestampMixin):
    """Maps an input drug name → canonical RxNorm metadata."""

    __tablename__ = "rxnorm_cache"
    __table_args__ = (
        UniqueConstraint("input_name_normalised", name="uq_rxnorm_input"),
        Index("ix_rxnorm_rxcui", "rxcui"),
    )

    # Stored lower-cased + whitespace-collapsed for case-insensitive matching
    input_name_normalised: Mapped[str] = mapped_column(String(256), nullable=False)
    # The original spelling the caller used — kept for logging
    input_name_original: Mapped[str] = mapped_column(String(256), nullable=False)
    rxcui: Mapped[str] = mapped_column(String(32), nullable=False)
    generic_name: Mapped[str] = mapped_column(String(256), nullable=False)
    brand_names: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    drug_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution_path: Mapped[str] = mapped_column(String(16), nullable=False)
    """exact | fuzzy | rxnorm_api"""
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)


class DrugQueryLog(Base, UUIDMixin, TimestampMixin):
    """One row per agent-endpoint request, for audit and analytics."""

    __tablename__ = "drug_query_log"
    __table_args__ = (
        Index("ix_drug_query_user_created", "user_id", "created_at"),
        Index("ix_drug_query_correlation", "correlation_id"),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    request_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # We DO NOT log the full response; just enough to debug
    success: Mapped[bool] = mapped_column(nullable=False, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RxNormSyncMarker(Base):
    """Records the SHA-256 of the last ingested raw/rxnorm/ bundle.

    Populated by ``services/drug-service/normalization/rxnorm_preload.py``
    (added in commit 2). The ``source_file`` is the cloud URI of the
    RxNorm bulk file.
    """

    __tablename__ = "rxnorm_sync_marker"
    source_file: Mapped[str] = mapped_column(String(512), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rows_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = ["DrugQueryLog", "RxNormCacheEntry", "RxNormSyncMarker"]
