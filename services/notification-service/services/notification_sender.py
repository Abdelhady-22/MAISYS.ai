"""NotificationSender — render + deliver + retry + persist.

This is the service-layer orchestrator. The HTTP route hands off
here and the route returns 202 immediately; this class then runs
the delivery in a background task.

Retry policy follows Part 5 §7.3 — three attempts with exponential
backoff. The default delays (60s, 300s, 1800s) reflect the spec
but are configurable so tests can use 0.01s delays.

A retry exhausts when:

* 3 attempts have been made, OR
* a non-retriable error is raised (template / config errors —
  retrying won't help)

After exhaustion the row is marked ``failed`` and the error is
recorded. Per Part 5 §7.3 a monitoring alert is intended; today
that's a structured log entry the operations stack can pick up.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.notification_service.exceptions.exceptions import (
    EmailDeliveryFailed,
    TemplateNameMismatch,
)
from services.notification_service.models.schemas import (
    Language,
    NotificationType,
    Priority,
    SendNotificationRequest,
)
from services.notification_service.repository.notification_repo import (
    NotificationRepository,
)
from services.notification_service.services.email_adapter import (
    EmailAdapter,
    EmailMessage,
)
from services.notification_service.services.template_renderer import render_email
from shared.logger import get_logger

_log = get_logger(__name__)


# Per Part 5 §7.3: 1 minute, 5 minutes, 30 minutes between attempts.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (60.0, 300.0, 1800.0)


class NotificationSender:
    """Orchestrator. One per service; safe to share across requests."""

    def __init__(
        self,
        *,
        email_adapter: EmailAdapter,
        session_factory: async_sessionmaker[AsyncSession],
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        self._email = email_adapter
        self._session_factory = session_factory
        self._retry_delays = tuple(retry_delays)
        self._background_tasks: set[asyncio.Task[None]] = set()
        # Keep references so tasks aren't GC'd mid-flight — Python's
        # asyncio docs explicitly warn about this.

    async def accept(self, request: SendNotificationRequest) -> str:
        """Persist the row, schedule delivery, return notification_id.

        Validation that's structural (Pydantic) happens before we get
        here. Cross-field validation (template_name == notification_type)
        is enforced here so the audit row gets the right values from
        the start.
        """
        if request.notification_type != request.template_name:
            raise TemplateNameMismatch(
                f"notification_type={request.notification_type!r} but "
                f"template_name={request.template_name!r}"
            )

        notification_id = uuid.uuid4().hex
        async with self._session_factory() as session:
            repo = NotificationRepository(session)
            await repo.create(
                notification_id=notification_id,
                notification_type=request.notification_type,
                user_id=request.user_id,
                recipient_email=str(request.recipient_email),
                language=request.language,
                correlation_id=request.correlation_id,
                priority=request.priority,
            )

        # Capture by value for the background task
        task = asyncio.create_task(
            self._deliver_with_retry(
                notification_id=notification_id,
                notification_type=request.notification_type,
                language=request.language,
                recipient_email=str(request.recipient_email),
                template_vars=request.template_vars,
                priority=request.priority,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return notification_id

    async def _deliver_with_retry(
        self,
        *,
        notification_id: str,
        notification_type: NotificationType,
        language: Language,
        recipient_email: str,
        template_vars: dict[str, Any],
        priority: Priority,
    ) -> None:
        """Render once, retry the send up to N times.

        Rendering errors are NOT retried — they're caller bugs. The
        delivery loop only retries adapter-side failures.
        """
        try:
            rendered = render_email(notification_type, language, template_vars)
        except Exception as exc:
            # Template errors are permanent — mark failed immediately.
            _log.warning(
                "notification.render_failed",
                notification_id=notification_id,
                error=str(exc),
            )
            async with self._session_factory() as session:
                await NotificationRepository(session).mark_failed(notification_id, f"render: {exc}")
            return

        message = EmailMessage(
            recipient=recipient_email,
            subject=rendered.subject,
            html_body=rendered.html_body,
            text_body=rendered.text_body,
        )

        # +1 because retry_delays counts BETWEEN attempts, not attempts.
        max_attempts = len(self._retry_delays) + 1
        last_error: str = "unknown"
        for attempt_idx in range(max_attempts):
            try:
                async with self._session_factory() as session:
                    await NotificationRepository(session).mark_delivering(notification_id)
                await self._email.send(message)
            except EmailDeliveryFailed as exc:
                last_error = str(exc)
                _log.info(
                    "notification.attempt_failed",
                    notification_id=notification_id,
                    attempt=attempt_idx + 1,
                    error=last_error,
                )
                async with self._session_factory() as session:
                    await NotificationRepository(session).record_attempt_error(
                        notification_id, last_error
                    )
                if attempt_idx + 1 >= max_attempts:
                    break
                await asyncio.sleep(self._retry_delays[attempt_idx])
                continue
            except Exception as exc:  # pragma: no cover — defensive
                last_error = f"unexpected: {exc}"
                _log.exception(
                    "notification.unexpected_error",
                    notification_id=notification_id,
                )
                break
            else:
                _log.info(
                    "notification.delivered",
                    notification_id=notification_id,
                    attempt=attempt_idx + 1,
                )
                async with self._session_factory() as session:
                    await NotificationRepository(session).mark_delivered(notification_id)
                return

        # If we fell through, all attempts exhausted.
        _log.warning(
            "notification.exhausted_retries",
            notification_id=notification_id,
            priority=priority,
            attempts=max_attempts,
            error=last_error,
        )
        async with self._session_factory() as session:
            await NotificationRepository(session).mark_failed(notification_id, last_error)

    async def wait_for_pending(self) -> None:
        """Test/shutdown helper: wait for in-flight deliveries to finish."""
        pending = list(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


__all__ = ["DEFAULT_RETRY_DELAYS", "NotificationSender"]
