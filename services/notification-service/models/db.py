"""SQLAlchemy ORM for notification-service.

Per Part 1 §7.10 the service has one table: ``notification_log``,
recording every send attempt. Extended fields below the catalog
definition (``attempts``, ``last_error``, ``correlation_id``,
``priority``) are pragmatic — they support the retry algorithm
(Part 5 §7.3) and don't widen the conceptual model.

The ``notification_preferences`` and ``suppression_list`` tables
referenced in the per-service CLAUDE.md are deferred (P3-C14) —
neither appears in Part 1 §7.10 or Part 5 §7.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    """Per-service declarative base — does NOT share metadata with
    other services. Each service owns its own database.
    """


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationLog(Base):
    """One row per send attempt.

    A single ``notification_id`` (UUID4 hex string) can have multiple
    DB rows if retries are recorded as separate inserts in the
    future; today we update one row in place and bump ``attempts``.
    """

    __tablename__ = "notification_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    """UUID4 hex string. Generated server-side on accept."""

    notification_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="en")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    """One of queued / delivering / delivered / failed."""

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")

    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["Base", "NotificationLog"]
