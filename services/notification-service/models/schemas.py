"""Pydantic schemas for notification-service.

The HTTP request body mirrors the RabbitMQ message format described
in Part 5 §7.1 — when RabbitMQ adoption lands later, the queue
consumer will accept the same shape and call the same internal send
function. Keeping the schemas aligned now avoids a contract break
later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Language = Literal["en", "ar"]
"""Two-letter ISO. Only English and Arabic are supported."""

NotificationType = Literal[
    "email_verify",
    "password_reset",
    "login_otp",
    "export_ready",
    "beta_session_reviewed",
]
"""The 5 templates enumerated in Part 5 §7.2. Adding a new
``notification_type`` requires both a template definition and a
schema entry — that coupling is deliberate, so an unknown
notification_type can't slip into production with no template."""

Priority = Literal["high", "normal", "low"]
"""Per Part 5 §7.1. Drives queue position when the RabbitMQ
consumer ships; today the priority field is recorded but treated
uniformly by the HTTP background-task scheduler."""

NotificationStatus = Literal[
    "queued",  # accepted, background task scheduled, no attempt yet
    "delivering",  # attempt in flight
    "delivered",  # SendGrid 2xx
    "failed",  # 3 attempts exhausted
]


# ─── /notifications/send ──────────────────────────────────────────


class SendNotificationRequest(BaseModel):
    """Body of ``POST /notifications/send``.

    Field-for-field mirror of the Part 5 §7.1 RabbitMQ payload so
    callers can swap transports without changing schemas.
    """

    model_config = ConfigDict(extra="forbid")

    notification_type: NotificationType
    user_id: str = Field(min_length=1, max_length=64)
    """User UUID (or other stable identifier). Recorded in the audit
    log; not used by the delivery path."""

    recipient_email: EmailStr
    language: Language = "en"
    template_name: NotificationType
    """Must match ``notification_type``. We accept both fields for
    parity with the queue payload (Part 5 §7.1) — having two
    matching fields would be redundant in pure HTTP, but the
    duplication is the contract."""

    template_vars: dict[str, Any] = Field(default_factory=dict)
    """Variables interpolated into the template. Validated against
    the per-template variable schema at render time."""

    correlation_id: str | None = None
    priority: Priority = "normal"


class SendNotificationResponse(BaseModel):
    """``POST /notifications/send`` returns 202 with this body."""

    model_config = ConfigDict(extra="forbid")

    notification_id: str
    status: NotificationStatus
    accepted_at: datetime


# ─── /notifications/{id} ──────────────────────────────────────────


class NotificationStatusResponse(BaseModel):
    """``GET /notifications/{id}`` body."""

    model_config = ConfigDict(extra="forbid")

    notification_id: str
    notification_type: NotificationType
    user_id: str
    recipient_email: str
    language: Language
    status: NotificationStatus
    attempts: int
    last_error: str | None = None
    accepted_at: datetime
    delivered_at: datetime | None = None


__all__ = [
    "Language",
    "NotificationStatus",
    "NotificationStatusResponse",
    "NotificationType",
    "Priority",
    "SendNotificationRequest",
    "SendNotificationResponse",
]
