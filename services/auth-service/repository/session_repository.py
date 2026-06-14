"""Session (refresh-token + JWT-jti) data access.

A session is one row per (user, refresh token). On refresh rotation, the
old row is revoked and a new one inserted — the old refresh token can
never re-issue a new access token.

Lookups go through indexed columns (jwt_jti, refresh_token_hash) so they
stay cheap even with many sessions per user.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Session


class SessionRepository:
    """Data access for the ``sessions`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Reads ────────────────────────────────────────────────────────
    async def get_by_id(self, session_id: UUID) -> Session | None:
        stmt = select(Session).where(Session.id == session_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_jti(self, jti: str) -> Session | None:
        stmt = select(Session).where(Session.jwt_jti == jti)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_refresh_hash(self, refresh_token_hash: str) -> Session | None:
        stmt = select(Session).where(Session.refresh_token_hash == refresh_token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID, *, only_active: bool = True) -> list[Session]:
        """List a user's sessions, newest first.

        ``only_active`` excludes revoked sessions and expired ones — the
        common case for ``GET /auth/sessions``. Pass False to inspect
        all history (admin use).
        """
        stmt = select(Session).where(Session.user_id == user_id).order_by(Session.issued_at.desc())
        if only_active:
            now = datetime.now(timezone.utc)
            stmt = stmt.where(Session.revoked.is_(False)).where(Session.expires_at > now)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Writes ───────────────────────────────────────────────────────
    async def create(
        self,
        *,
        user_id: UUID,
        jwt_jti: str,
        refresh_token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> Session:
        new_session = Session(
            user_id=user_id,
            jwt_jti=jwt_jti,
            refresh_token_hash=refresh_token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            revoked=False,
        )
        self._session.add(new_session)
        await self._session.flush()
        return new_session

    async def revoke(self, session_id: UUID) -> None:
        """Idempotent — revoking an already-revoked session is a no-op."""
        await self._session.execute(
            update(Session)
            .where(Session.id == session_id)
            .where(Session.revoked.is_(False))
            .values(revoked=True, revoked_at=datetime.now(timezone.utc))
        )

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revoke every active session for a user. Returns count revoked."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            update(Session)
            .where(Session.user_id == user_id)
            .where(Session.revoked.is_(False))
            .values(revoked=True, revoked_at=now)
        )
        # ``rowcount`` is provided by the underlying CursorResult for DML
        # statements but isn't visible on the generic Result type that
        # mypy infers — cast explicitly.
        return int(result.rowcount)  # type: ignore[attr-defined]


__all__ = ["SessionRepository"]
