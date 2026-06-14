"""Password reset token data access — single-use, time-limited tokens."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import PasswordReset


class PasswordResetRepository:
    """Data access for ``password_resets``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> PasswordReset | None:
        stmt = select(PasswordReset).where(PasswordReset.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordReset:
        reset = PasswordReset(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            used=False,
        )
        self._session.add(reset)
        await self._session.flush()
        return reset

    async def mark_used(self, reset_id: UUID) -> None:
        await self._session.execute(
            update(PasswordReset)
            .where(PasswordReset.id == reset_id)
            .values(used=True, used_at=datetime.now(timezone.utc))
        )


__all__ = ["PasswordResetRepository"]
