"""Email delivery — stub for Session B.

The real email pipeline lives in ``email-service`` (P2-T*) and uses
SendGrid/SES. Until that service is online, this stub logs the outbound
message so flows can be exercised end-to-end without a real SMTP
provider.

When email-service ships, swap the implementation here to POST the
payload to its ``/email/send`` endpoint via the existing
``services/auth-service/services`` factory.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from shared.logger import get_logger

_log = get_logger(__name__)


EmailKind = Literal["otp_email_verify", "otp_login", "password_reset"]


class EmailService:
    """Stub: logs what would be sent rather than dispatching to SMTP."""

    async def send_otp(
        self,
        *,
        to_email: str,
        code: str,
        kind: EmailKind,
        user_id: UUID,
        language: str = "en",
    ) -> None:
        """Send a one-time code via email.

        The raw OTP code IS passed here (not the hash) — this is the
        only place in the codebase that handles plaintext codes besides
        the generation site. The logger has scrub_sensitive in its
        processor chain, so the literal code is redacted before reaching
        the log sink.
        """
        _log.info(
            "email.otp.would_send",
            to_email=to_email,
            kind=kind,
            user_id=str(user_id),
            language=language,
            code=code,  # scrubbed by structlog processor
        )

    async def send_password_reset(
        self,
        *,
        to_email: str,
        reset_token: str,
        user_id: UUID,
        language: str = "en",
    ) -> None:
        """Send a password-reset link containing the raw token."""
        _log.info(
            "email.password_reset.would_send",
            to_email=to_email,
            user_id=str(user_id),
            language=language,
            reset_token=reset_token,  # scrubbed
        )


__all__ = ["EmailKind", "EmailService"]
