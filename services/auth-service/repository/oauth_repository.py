"""OAuth account data access — Google/Apple identity links."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import OAuthAccount


class OAuthAccountRepository:
    """Data access for ``oauth_accounts``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_provider_and_id(
        self, provider: str, provider_user_id: str
    ) -> OAuthAccount | None:
        """Find by (provider, provider's stable user id).

        Indexed by the composite unique constraint; the primary path the
        OAuth callback takes to decide login vs signup.
        """
        stmt = (
            select(OAuthAccount)
            .where(OAuthAccount.provider == provider)
            .where(OAuthAccount.provider_user_id == provider_user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[OAuthAccount]:
        stmt = select(OAuthAccount).where(OAuthAccount.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_user_id: str,
        provider_email: str | None,
    ) -> OAuthAccount:
        oauth = OAuthAccount(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )
        self._session.add(oauth)
        await self._session.flush()
        return oauth


__all__ = ["OAuthAccountRepository"]
