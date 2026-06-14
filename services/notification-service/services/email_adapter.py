"""Email delivery adapter — Protocol + SendGrid + Fake.

The ``EmailAdapter`` protocol lets the orchestrator stay agnostic
of which provider is configured. SendGrid is the production path
per Part 1 §7.10; the Fake is what tests inject so they don't need
a network sandbox or real API keys.

SMTP fallback (Part 5 §7.3) is intentionally NOT implemented in
this PR — only one provider is wired today. SendGrid handles the
primary case; adding ``SMTPEmailAdapter`` alongside is a follow-up
once we have an SMTP relay in the stack. Documented in P3-C15.

The adapter signature is deliberately minimal:

* Inputs: recipient, subject, html body, text body.
* Output: nothing on success; raise ``EmailDeliveryFailed`` on any
  failure the caller should retry on.

Everything beyond that (templating, retry, persistence) lives in
``notification_sender.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from services.notification_service.exceptions.exceptions import EmailDeliveryFailed
from shared.logger import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    recipient: str
    subject: str
    html_body: str
    text_body: str


class EmailAdapter(Protocol):
    """Protocol the orchestrator depends on."""

    async def send(self, message: EmailMessage) -> None:
        """Deliver one message. Raise ``EmailDeliveryFailed`` to retry."""
        ...


# ─── SendGrid ────────────────────────────────────────────────────


class SendGridAdapter:
    """Production adapter — sends via SendGrid's REST API.

    SendGrid is imported lazily so this module stays importable on
    workstations without the SDK. The constructor reads the API key
    from the env so the wiring layer doesn't have to thread it.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        from_email: str | None = None,
        from_name: str = "MAISYS",
    ) -> None:
        self._api_key = api_key or os.environ.get("SENDGRID_API_KEY", "")
        self._from_email = from_email or os.environ.get("EMAIL_FROM", "no-reply@maisys.io")
        self._from_name = from_name

    async def send(self, message: EmailMessage) -> None:
        if not self._api_key:
            raise EmailDeliveryFailed("SendGrid API key not configured")

        try:
            # Lazy import — sendgrid is a heavy dependency for tests.
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Content, Email, Mail, To
        except ImportError as exc:
            raise EmailDeliveryFailed(f"sendgrid SDK not installed: {exc}") from exc

        mail = Mail(
            from_email=Email(self._from_email, self._from_name),
            to_emails=To(message.recipient),
            subject=message.subject,
        )
        # Plain text first, then HTML — SendGrid recommends this ordering.
        mail.add_content(Content("text/plain", message.text_body))
        mail.add_content(Content("text/html", message.html_body))

        client = SendGridAPIClient(self._api_key)
        try:
            # SendGridAPIClient.send is sync. Run it off the event loop.
            import asyncio

            response = await asyncio.to_thread(client.send, mail)
        except Exception as exc:
            _log.warning("email.sendgrid.error", error=str(exc))
            raise EmailDeliveryFailed(f"SendGrid call failed: {exc}") from exc

        status_code = getattr(response, "status_code", 0)
        if status_code < 200 or status_code >= 300:
            _log.warning(
                "email.sendgrid.non_2xx",
                status_code=status_code,
                body=getattr(response, "body", b"")[:200],
            )
            raise EmailDeliveryFailed(f"SendGrid returned {status_code} for {message.recipient}")


# ─── Fake (for tests) ────────────────────────────────────────────


class FakeEmailAdapter:
    """In-memory adapter that records every send for assertions.

    Configurable to fail the first N calls — used to test the retry
    path without network or real timing.
    """

    def __init__(self, *, fail_first_n: int = 0) -> None:
        self.sent: list[EmailMessage] = []
        self.attempts = 0
        self._fail_first_n = fail_first_n

    async def send(self, message: EmailMessage) -> None:
        self.attempts += 1
        if self.attempts <= self._fail_first_n:
            raise EmailDeliveryFailed(f"Simulated failure on attempt {self.attempts}")
        self.sent.append(message)


__all__ = [
    "EmailAdapter",
    "EmailMessage",
    "FakeEmailAdapter",
    "SendGridAdapter",
]
