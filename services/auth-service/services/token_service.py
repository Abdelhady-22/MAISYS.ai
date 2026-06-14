"""Refresh-token rotation and logout.

Refresh rotation: every refresh request invalidates the current session
and creates a brand-new one. The old refresh token can never reissue a
new access token. This is the security best practice for opaque refresh
tokens.

Logout: revokes the session identified by the access token's ``jti``.
Idempotent — logging out twice is a no-op the second time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    InvalidRefreshTokenException,
    RefreshTokenExpiredException,
)
from repository import AuditRepository, SessionRepository, UserRepository
from shared.auth import Role
from utils.jwt import issue_access_token
from utils.tokens import generate_refresh_token, hash_refresh_token


@dataclass
class RefreshedTokens:
    """Output of a successful refresh — new access + new refresh tokens."""

    access_token: str
    refresh_token: str
    expires_in: int


class TokenService:
    """Refresh and logout flows."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._users = UserRepository(db)
        self._sessions = SessionRepository(db)
        self._audit = AuditRepository(db)

    # ── Refresh rotation ────────────────────────────────────────────
    async def refresh(
        self,
        *,
        refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RefreshedTokens:
        token_hash = hash_refresh_token(refresh_token)
        old = await self._sessions.get_by_refresh_hash(token_hash)
        if old is None:
            await self._audit.log(
                action="token.refresh.unknown",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidRefreshTokenException("Refresh token not recognised")

        if old.revoked:
            # Reuse of a revoked token is a strong signal of compromise.
            # Defence-in-depth: revoke ALL active sessions for this user.
            await self._sessions.revoke_all_for_user(old.user_id)
            await self._audit.log(
                action="token.refresh.reuse_revoked",
                user_id=old.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"original_session_id": str(old.id)},
            )
            await self._db.commit()
            raise InvalidRefreshTokenException("Refresh token has been revoked")

        now = datetime.now(timezone.utc)
        # Normalise old.expires_at to a timezone-aware datetime — SQLite
        # round-trips DateTime(timezone=True) as naive on read.
        expires_at = old.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            await self._audit.log(
                action="token.refresh.expired",
                user_id=old.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise RefreshTokenExpiredException("Refresh token has expired")

        # Look up the user (role may have changed since the token was
        # issued — always re-read).
        user = await self._users.get_by_id(old.user_id)
        if user is None or not user.is_active or user.locked_at is not None:
            await self._sessions.revoke(old.id)
            await self._audit.log(
                action="token.refresh.user_unavailable",
                user_id=old.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._db.commit()
            raise InvalidRefreshTokenException("Account is no longer eligible for refresh")

        # Revoke the old session and create a new one.
        await self._sessions.revoke(old.id)
        expire_minutes = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        refresh_days = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
        role = Role(user.role)
        access_token, new_jti = issue_access_token(str(user.id), role)
        new_refresh = generate_refresh_token()
        await self._sessions.create(
            user_id=user.id,
            jwt_jti=new_jti,
            refresh_token_hash=hash_refresh_token(new_refresh),
            issued_at=now,
            expires_at=now + timedelta(days=refresh_days),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self._audit.log(
            action="token.refresh.success",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"rotated_from_session_id": str(old.id)},
        )
        await self._db.commit()
        return RefreshedTokens(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_in=expire_minutes * 60,
        )

    # ── Logout ──────────────────────────────────────────────────────
    async def logout(
        self,
        *,
        jwt_jti: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Revoke the session matching ``jwt_jti``. Idempotent."""
        session = await self._sessions.get_by_jti(jwt_jti)
        if session is None:
            # Already gone / never existed — still treat as success so
            # logout never errors and never leaks session existence.
            await self._audit.log(
                action="user.logout.unknown_jti",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._db.commit()
            return
        await self._sessions.revoke(session.id)
        await self._audit.log(
            action="user.logout",
            user_id=session.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"session_id": str(session.id)},
        )
        await self._db.commit()


__all__ = ["RefreshedTokens", "TokenService"]
