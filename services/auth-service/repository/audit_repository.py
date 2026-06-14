"""Audit log data access — append-only.

Audit records are written by every sensitive endpoint (registration,
password reset confirm, profile patch, session revoke, OAuth callback).
The schema is intentionally permissive on ``user_id`` (nullable) so
pre-login events (failed registration, password reset request for an
unknown email) can also be recorded.

``created_at`` is set explicitly in Python time (with microsecond
precision) rather than relying on the database's ``CURRENT_TIMESTAMP``,
which has 1-second resolution on SQLite. This keeps ordering
deterministic in tests and across dialects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import AuditLog


class AuditRepository:
    """Data access for ``audit_log``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        action: str,
        user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Write an audit record. Returns the created row.

        ``details`` is JSONB on Postgres / JSON on SQLite. Callers should
        keep it small (≤ a few kB); large payloads go to log aggregators.
        """
        record = AuditLog(
            action=action,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_for_user(self, user_id: UUID, *, limit: int = 50) -> list[AuditLog]:
        """Return the most-recent audit rows for a user, newest first.

        Used by an admin endpoint (future) for forensic queries. Capped
        so a single query can't pull all of history.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["AuditRepository"]
