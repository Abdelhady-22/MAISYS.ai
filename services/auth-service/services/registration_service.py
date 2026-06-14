"""User registration and email-verification flow.

Two methods:

* ``register`` — validates uniqueness, hashes the password, creates the
  user (with email_verified=False), issues an email-verify OTP, audits
  the event, returns user_id.

* ``verify_email`` — validates an OTP submission against the latest
  active email-verify code for the user; on success flips
  email_verified to True and audits.

The OTP transport is the email_service stub for now (Session C wires the
real email-service). OTP attempts are limited (3 per code, per
Clarifications Log C9): on the third wrong attempt the OTP is
invalidated and a fresh one must be requested.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    EmailAlreadyExistsException,
    OTPExpiredException,
    OTPInvalidException,
    OTPMaxAttemptsException,
)
from repository import AuditRepository, OTPRepository, UserRepository
from services.email_service import EmailService
from utils.otp import generate_otp, hash_otp, verify_otp
from utils.password import hash_password


class RegistrationService:
    """Orchestrates registration and email-verification."""

    def __init__(
        self,
        db: AsyncSession,
        email_service: EmailService | None = None,
    ) -> None:
        self._db = db
        self._users = UserRepository(db)
        self._otps = OTPRepository(db)
        self._audit = AuditRepository(db)
        self._email = email_service or EmailService()

    # ── Register ─────────────────────────────────────────────────────
    async def register(
        self,
        *,
        email: str,
        password: str,
        language_preference: str = "en",
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UUID:
        """Create a new user, issue an email-verify OTP, return user_id.

        Raises ``EmailAlreadyExistsException`` if the email is in use.
        The exception leaks email existence — this is documented in the
        task spec (it's the explicit error code on this endpoint) and
        is a deliberate UX vs. enumeration trade-off.
        """
        existing = await self._users.get_by_email(email)
        if existing is not None:
            await self._audit.log(
                action="user.register.duplicate",
                user_id=None,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"email_hash": existing.email_hash},
            )
            raise EmailAlreadyExistsException(f"Email already registered: {email}")

        password_hash_str = hash_password(password)
        user = await self._users.create(
            email=email,
            password_hash=password_hash_str,
            language_preference=language_preference,
        )

        # Issue verification OTP
        code = generate_otp()
        otp_ttl_minutes = int(os.environ.get("OTP_EXPIRE_MINUTES", "10"))
        await self._otps.create(
            user_id=user.id,
            code_hash=hash_otp(code),
            purpose="email_verify",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=otp_ttl_minutes),
        )
        await self._email.send_otp(
            to_email=user.email,
            code=code,
            kind="otp_email_verify",
            user_id=user.id,
            language=language_preference,
        )

        await self._audit.log(
            action="user.registered",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"language_preference": language_preference},
        )

        await self._db.commit()
        return UUID(str(user.id))

    # ── Verify email ─────────────────────────────────────────────────
    async def verify_email(
        self,
        *,
        user_id: UUID,
        code: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Verify an email-verify OTP. Idempotent if email already verified.

        Distinguishes three failure modes:
        * No active OTP / expired → ``OTPExpiredException``
        * Code doesn't match → ``OTPInvalidException`` (counts as attempt)
        * Max attempts reached → ``OTPMaxAttemptsException`` (invalidates OTP)
        """
        max_attempts = int(os.environ.get("OTP_MAX_ATTEMPTS", "3"))

        active = await self._otps.get_active(user_id, purpose="email_verify")
        if active is None:
            await self._audit.log(
                action="user.email_verify.expired_or_missing",
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise OTPExpiredException("No active email-verification code; request a new one")

        if not verify_otp(code, active.code_hash):
            new_attempts = await self._otps.increment_attempt(active.id)
            if new_attempts >= max_attempts:
                await self._otps.invalidate(active.id)
                await self._audit.log(
                    action="user.email_verify.max_attempts",
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={"attempts": new_attempts},
                )
                await self._db.commit()
                raise OTPMaxAttemptsException("Too many failed attempts; request a new code")
            await self._audit.log(
                action="user.email_verify.invalid",
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"attempt": new_attempts},
            )
            await self._db.commit()
            raise OTPInvalidException("Code does not match")

        # Success — mark OTP used and user verified
        await self._otps.mark_used(active.id)
        await self._users.mark_email_verified(user_id)
        await self._audit.log(
            action="user.email_verified",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._db.commit()


__all__ = ["RegistrationService"]
