"""Login flow with failed-attempt lockout.

Decision tree on POST /auth/login:

1. Lookup user by email — if not found, audit and raise
   ``InvalidCredentialsException`` (same code as bad password — no email
   enumeration).
2. If user is locked, raise ``AccountLockedException``.
3. If not ``is_active``, raise ``AccountDeactivatedException``.
4. Verify password. On mismatch, increment ``failed_login_attempts``;
   if the new count reaches the lockout threshold (default 5), lock the
   account. Either way, raise ``InvalidCredentialsException``.
5. If not ``email_verified``, raise ``EmailNotVerifiedException``.
6. If the user's role triggers the optional OTP gate (admin /
   super_admin by default), issue a login-OTP and return an
   ``otp_required`` response with a temporary OTP token. The user then
   POSTs ``/auth/verify-otp`` to complete login.
7. Otherwise, issue access + refresh tokens, persist the session, audit,
   and return the token pair.

The OTP gate is configurable via ``LOGIN_OTP_REQUIRED_ROLES`` env var
(comma-separated list of role names; default ``"admin,super_admin"``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    AccountDeactivatedException,
    AccountLockedException,
    EmailNotVerifiedException,
    InvalidCredentialsException,
)
from models.db import User
from repository import (
    AuditRepository,
    OTPRepository,
    SessionRepository,
    UserRepository,
)
from services.email_service import EmailService
from shared.auth import Role
from utils.jwt import issue_access_token
from utils.otp import generate_otp, hash_otp
from utils.password import verify_password
from utils.tokens import generate_refresh_token, hash_refresh_token


@dataclass
class LoginTokens:
    """Successful-login result. Contains everything the route needs to
    build the LoginResponse schema."""

    access_token: str
    refresh_token: str
    expires_in: int
    user: User


@dataclass
class LoginOTPRequired:
    """OTP-gate result. The user must complete OTP verification before
    tokens are issued."""

    user_id: UUID
    message: str


# Output of a login attempt is one of two shapes — the route translates
# to the appropriate Pydantic response model.
LoginResult = LoginTokens | LoginOTPRequired


class LoginService:
    """Orchestrates password authentication and the OTP gate."""

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

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_info: str | None = None,
    ) -> LoginResult:
        max_failed = int(os.environ.get("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
        otp_roles_env = os.environ.get("LOGIN_OTP_REQUIRED_ROLES", "admin,super_admin")
        otp_roles = {r.strip() for r in otp_roles_env.split(",") if r.strip()}

        # 1. Lookup user
        user = await self._users.get_by_email(email)
        if user is None:
            await self._audit.log(
                action="user.login.unknown_email",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidCredentialsException("Invalid email or password")

        # 2. Locked
        if user.locked_at is not None:
            await self._audit.log(
                action="user.login.locked",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AccountLockedException("Account is locked")

        # 3. Deactivated
        if not user.is_active:
            await self._audit.log(
                action="user.login.deactivated",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AccountDeactivatedException("Account is deactivated")

        # 4. Password
        if user.password_hash is None or not verify_password(user.password_hash, password):
            new_count = await self._users.increment_failed_logins(user.id)
            now_locked = new_count >= max_failed
            if now_locked:
                await self._users.lock_account(user.id)
            await self._audit.log(
                action="user.login.bad_password",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"attempt": new_count, "locked": now_locked},
            )
            await self._db.commit()
            if now_locked:
                raise AccountLockedException("Too many failed attempts; account locked")
            raise InvalidCredentialsException("Invalid email or password")

        # 5. Email verified
        if not user.email_verified:
            await self._audit.log(
                action="user.login.email_not_verified",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise EmailNotVerifiedException("Email not verified")

        # 6. OTP gate — only for roles in LOGIN_OTP_REQUIRED_ROLES.
        if user.role in otp_roles:
            code = generate_otp()
            otp_ttl_minutes = int(os.environ.get("OTP_EXPIRE_MINUTES", "10"))
            await self._otps.create(
                user_id=user.id,
                code_hash=hash_otp(code),
                purpose="login_otp",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=otp_ttl_minutes),
            )
            await self._email.send_otp(
                to_email=user.email,
                code=code,
                kind="otp_login",
                user_id=user.id,
                language=user.language_preference,
            )
            await self._audit.log(
                action="user.login.otp_required",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._db.commit()
            return LoginOTPRequired(
                user_id=user.id,
                message="OTP sent to your email. Complete with /auth/verify-otp.",
            )

        # 7. Happy path — issue tokens, create session
        return await self._issue_tokens(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info=device_info,
            audit_action="user.login.success",
        )

    async def _issue_tokens(
        self,
        *,
        user: User,
        ip_address: str | None,
        user_agent: str | None,
        device_info: str | None,
        audit_action: str,
    ) -> LoginTokens:
        """Common token-issuance path — also reused by OTP-completed login."""
        expire_minutes = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        refresh_days = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

        role = Role(user.role)
        access_token, jti = issue_access_token(str(user.id), role)
        refresh_token = generate_refresh_token()
        now = datetime.now(timezone.utc)
        await self._sessions.create(
            user_id=user.id,
            jwt_jti=jti,
            refresh_token_hash=hash_refresh_token(refresh_token),
            issued_at=now,
            expires_at=now + timedelta(days=refresh_days),
            user_agent=user_agent or device_info,
            ip_address=ip_address,
        )
        await self._users.update_last_login(user.id)
        await self._audit.log(
            action=audit_action,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._db.commit()
        # Refresh the user so language_preference / role reflect the
        # latest state if anything mutated during the call (it didn't,
        # but be defensive).
        await self._db.refresh(user)
        return LoginTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expire_minutes * 60,
            user=user,
        )

    # ── Complete login after OTP ─────────────────────────────────────
    async def complete_otp_login(
        self,
        *,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LoginTokens:
        """Called by verify_otp when purpose='login_otp' succeeds.

        We can assume the OTP has already been verified and marked used
        by the caller — this method just issues tokens.
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            # Shouldn't happen — the OTP could only be valid for an
            # existing user — but be defensive.
            raise InvalidCredentialsException("User no longer exists")
        return await self._issue_tokens(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info=None,
            audit_action="user.login.otp_success",
        )


__all__ = ["LoginOTPRequired", "LoginResult", "LoginService", "LoginTokens"]
