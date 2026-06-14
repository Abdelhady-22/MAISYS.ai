"""OTP code data access.

Lifecycle of a single OTP:
1. ``create`` — write a new code_hash row with attempt_count=0, used=False
2. ``get_active`` — most-recent unused, non-expired code for a (user, purpose)
3. ``increment_attempt`` — bump the counter on every verification attempt
4. On success: ``mark_used``; on max attempts: ``invalidate`` (sets used=True)

The hash itself is computed by ``utils.otp``; this repository only stores
and looks up the hash.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import OTPCode


class OTPRepository:
    """Data access for ``otp_codes``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, otp_id: UUID) -> OTPCode | None:
        stmt = select(OTPCode).where(OTPCode.id == otp_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self, user_id: UUID, purpose: str) -> OTPCode | None:
        """Most recent unused, non-expired OTP for this (user, purpose).

        Used by the verify-otp route to find the row to compare the
        incoming code against. There may be multiple active codes if the
        user requested several resends — we always use the newest.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(OTPCode)
            .where(OTPCode.user_id == user_id)
            .where(OTPCode.purpose == purpose)
            .where(OTPCode.used.is_(False))
            .where(OTPCode.expires_at > now)
            .order_by(desc(OTPCode.created_at))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: UUID,
        code_hash: str,
        purpose: str,
        expires_at: datetime,
    ) -> OTPCode:
        otp = OTPCode(
            user_id=user_id,
            code_hash=code_hash,
            purpose=purpose,
            expires_at=expires_at,
            used=False,
            attempt_count=0,
        )
        self._session.add(otp)
        await self._session.flush()
        return otp

    async def increment_attempt(self, otp_id: UUID) -> int:
        """Bump the counter, return the new attempt count.

        Read-then-write (same pattern as failed_login_attempts). The
        small race window is acceptable — over-counting just locks the
        OTP faster, which is the safer direction.
        """
        otp = await self.get_by_id(otp_id)
        if otp is None:
            return 0
        otp.attempt_count = (otp.attempt_count or 0) + 1
        await self._session.flush()
        return otp.attempt_count

    async def mark_used(self, otp_id: UUID) -> None:
        await self._session.execute(
            update(OTPCode)
            .where(OTPCode.id == otp_id)
            .values(used=True, used_at=datetime.now(timezone.utc))
        )

    async def invalidate(self, otp_id: UUID) -> None:
        """Mark used without success (e.g. after max attempts). Same as
        mark_used at the schema level — the distinction is semantic, not
        structural."""
        await self.mark_used(otp_id)


__all__ = ["OTPRepository"]
