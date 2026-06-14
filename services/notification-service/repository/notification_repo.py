"""Repository for ``notification_log``.

The repository is the only layer that touches SQLAlchemy. Services
call clean domain methods (``create``, ``get_by_id``,
``mark_delivering``, etc.) and receive ORM objects back — but they
must NEVER return ORM objects to the routes; the routes get
Pydantic schemas from the service layer (per services/CLAUDE.md
all-services standards).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.notification_service.models.db import NotificationLog


class NotificationRepository:
    """Thin async wrapper around ``notification_log``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        notification_id: str,
        notification_type: str,
        user_id: str,
        recipient_email: str,
        language: str,
        correlation_id: str | None,
        priority: str,
    ) -> NotificationLog:
        row = NotificationLog(
            id=notification_id,
            notification_type=notification_type,
            user_id=user_id,
            recipient_email=recipient_email,
            language=language,
            status="queued",
            attempts=0,
            last_error=None,
            correlation_id=correlation_id,
            priority=priority,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get_by_id(self, notification_id: str) -> NotificationLog | None:
        stmt = select(NotificationLog).where(NotificationLog.id == notification_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_delivering(self, notification_id: str) -> None:
        row = await self._must_get(notification_id)
        row.status = "delivering"
        row.attempts = row.attempts + 1
        await self._session.commit()

    async def mark_delivered(self, notification_id: str) -> None:
        row = await self._must_get(notification_id)
        row.status = "delivered"
        row.last_error = None
        row.delivered_at = datetime.now(timezone.utc)
        await self._session.commit()

    async def mark_failed(self, notification_id: str, error: str) -> None:
        row = await self._must_get(notification_id)
        row.status = "failed"
        row.last_error = error[:2000]  # truncate to avoid Text overflow
        await self._session.commit()

    async def record_attempt_error(self, notification_id: str, error: str) -> None:
        """Used during retries — bumps attempts and records the most
        recent error without flipping the row to ``failed`` (the
        retry loop decides when to do that)."""
        row = await self._must_get(notification_id)
        row.last_error = error[:2000]
        await self._session.commit()

    async def _must_get(self, notification_id: str) -> NotificationLog:
        row = await self.get_by_id(notification_id)
        if row is None:
            raise LookupError(f"notification_log row not found: {notification_id}")
        return row


__all__ = ["NotificationRepository"]
