"""Profile and session-management business logic.

Covers:
* ``GET /auth/me`` — full profile (joins users + user_profiles)
* ``PATCH /auth/me`` — partial update; email changes trigger
  re-verification
* ``GET /auth/sessions`` — list active sessions for the user
* ``DELETE /auth/sessions/{id}`` — revoke a specific session
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    EmailAlreadyExistsException,
    SessionNotFoundException,
)
from models.db import Session as SessionModel
from models.db import User
from repository import (
    AuditRepository,
    OTPRepository,
    SessionRepository,
    UserRepository,
)
from services.email_service import EmailService
from utils.otp import generate_otp, hash_otp


@dataclass
class ProfileSnapshot:
    """All fields needed for MeResponse — flattened across users + profile."""

    user: User
    display_name: str | None
    avatar_url: str | None


@dataclass
class UpdateProfileResult:
    snapshot: ProfileSnapshot
    email_reverification_required: bool
    message: str | None


class ProfileService:
    """Profile read/update and session management."""

    def __init__(
        self,
        db: AsyncSession,
        email_service: EmailService | None = None,
    ) -> None:
        self._db = db
        self._users = UserRepository(db)
        self._sessions = SessionRepository(db)
        self._otps = OTPRepository(db)
        self._audit = AuditRepository(db)
        self._email = email_service or EmailService()

    async def get_me(self, user_id: UUID) -> ProfileSnapshot:
        user = await self._users.get_by_id(user_id)
        if user is None:
            # The dependency layer should have already failed
            # authentication before we get here; treat as session-not-
            # found if it slips through.
            raise SessionNotFoundException("User not found")
        await self._db.refresh(user, ["profile"])
        return ProfileSnapshot(
            user=user,
            display_name=user.profile.display_name if user.profile else None,
            avatar_url=user.profile.avatar_url if user.profile else None,
        )

    async def update_profile(
        self,
        *,
        user_id: UUID,
        email: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
        language_preference: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UpdateProfileResult:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise SessionNotFoundException("User not found")

        email_reverification = False
        change_details: dict[str, object] = {}

        # Email change is the only multi-step path.
        if email is not None and email.strip().lower() != user.email:
            other = await self._users.get_by_email(email)
            if other is not None and other.id != user_id:
                raise EmailAlreadyExistsException(f"Email already in use: {email}")
            await self._users.update_email(user_id, email)
            change_details["email_changed"] = True

            # Issue a fresh email-verify OTP for the new address.
            code = generate_otp()
            otp_ttl_minutes = int(os.environ.get("OTP_EXPIRE_MINUTES", "10"))
            await self._otps.create(
                user_id=user_id,
                code_hash=hash_otp(code),
                purpose="email_verify",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=otp_ttl_minutes),
            )
            await self._email.send_otp(
                to_email=email,
                code=code,
                kind="otp_email_verify",
                user_id=user_id,
                language=language_preference or user.language_preference,
            )
            email_reverification = True

        # Other profile patches.
        if display_name is not None or avatar_url is not None or language_preference is not None:
            await self._users.update_profile(
                user_id,
                display_name=display_name,
                avatar_url=avatar_url,
                language_preference=language_preference,
            )
            if display_name is not None:
                change_details["display_name_changed"] = True
            if avatar_url is not None:
                change_details["avatar_url_changed"] = True
            if language_preference is not None:
                change_details["language_changed"] = True

        await self._audit.log(
            action="user.profile.updated",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=change_details,
        )
        await self._db.commit()

        # Refresh and return.
        snapshot = await self.get_me(user_id)
        message = "Email changed — please verify the new address." if email_reverification else None
        return UpdateProfileResult(
            snapshot=snapshot,
            email_reverification_required=email_reverification,
            message=message,
        )

    async def list_sessions(self, user_id: UUID) -> list[SessionModel]:
        return await self._sessions.list_for_user(user_id, only_active=True)

    async def revoke_session(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        target = await self._sessions.get_by_id(session_id)
        if target is None or target.user_id != user_id:
            # Same code for "wrong user" and "doesn't exist" — don't
            # confirm session ids belonging to other users.
            raise SessionNotFoundException("Session not found")
        await self._sessions.revoke(session_id)
        await self._audit.log(
            action="session.revoked",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"session_id": str(session_id)},
        )
        await self._db.commit()


__all__ = ["ProfileService", "ProfileSnapshot", "UpdateProfileResult"]
