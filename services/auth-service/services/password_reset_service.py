"""Password-reset request and confirm flow.

Security properties enforced:

* The ``request`` endpoint must NOT leak whether an email is registered.
  Always returns a generic 200 message regardless of lookup result.
* The reset token is opaque random 32 bytes (URL-safe base64), stored
  as SHA-256 hash. Raw token only exists in the outbound email.
* Single-use: the token is marked ``used`` immediately on a successful
  confirm.
* On confirm, ALL active sessions for the user are revoked (forces
  re-login everywhere — appropriate after a password change of any
  kind).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    InvalidPasswordFormatException,
)
from repository import (
    AuditRepository,
    PasswordResetRepository,
    SessionRepository,
    UserRepository,
)
from services.email_service import EmailService
from utils.password import hash_password
from utils.tokens import generate_refresh_token, hash_refresh_token


class PasswordResetService:
    """Request and confirm-side of the password-reset flow."""

    def __init__(
        self,
        db: AsyncSession,
        email_service: EmailService | None = None,
    ) -> None:
        self._db = db
        self._users = UserRepository(db)
        self._resets = PasswordResetRepository(db)
        self._sessions = SessionRepository(db)
        self._audit = AuditRepository(db)
        self._email = email_service or EmailService()

    # ── Request ──────────────────────────────────────────────────────
    async def request_reset(
        self,
        *,
        email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Issue a reset token if the email exists; otherwise silently
        return. The HTTP layer always responds with a generic 200.
        """
        user = await self._users.get_by_email(email)
        if user is None:
            await self._audit.log(
                action="password_reset.request.unknown_email",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._db.commit()
            return

        # Issue a fresh random token; store the hash, send the raw value.
        raw_token = generate_refresh_token()  # reuse the 32-byte generator
        ttl_minutes = int(os.environ.get("PASSWORD_RESET_TTL_MINUTES", "30"))
        await self._resets.create(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        )
        await self._email.send_password_reset(
            to_email=user.email,
            reset_token=raw_token,
            user_id=user.id,
            language=user.language_preference,
        )
        await self._audit.log(
            action="password_reset.request.issued",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._db.commit()

    # ── Confirm ──────────────────────────────────────────────────────
    async def confirm_reset(
        self,
        *,
        token: str,
        new_password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Consume a reset token and set a new password.

        Failure surfaces as ``InvalidPasswordFormatException`` (code
        ``INVALID_PASSWORD_FORMAT``) for unknown/used/expired tokens —
        intentionally vague to avoid revealing token state to an
        attacker. The Pydantic schema enforces password complexity
        before we get here.
        """
        token_hash = hash_refresh_token(token)
        reset = await self._resets.get_by_token_hash(token_hash)
        if reset is None or reset.used:
            await self._audit.log(
                action="password_reset.confirm.invalid_token",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._db.commit()
            raise InvalidPasswordFormatException("Invalid or used reset token")

        expires_at = reset.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            await self._audit.log(
                action="password_reset.confirm.expired_token",
                user_id=reset.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._db.commit()
            raise InvalidPasswordFormatException("Reset token has expired")

        # Apply the new password and consume the token.
        await self._users.update_password(reset.user_id, hash_password(new_password))
        await self._resets.mark_used(reset.id)

        # Revoke all sessions — force re-login everywhere after a
        # password change (defence in depth against compromised tokens).
        revoked_count = await self._sessions.revoke_all_for_user(reset.user_id)
        await self._audit.log(
            action="password_reset.confirm.success",
            user_id=reset.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"sessions_revoked": revoked_count},
        )
        await self._db.commit()


__all__ = ["PasswordResetService"]
