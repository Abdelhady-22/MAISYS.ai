"""Tests for OAuthAccountRepository."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User

from repository.oauth_repository import OAuthAccountRepository
from repository.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "u@example.com") -> User:
    repo = UserRepository(db_session)
    user = await repo.create(email=email, password_hash=None)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_create_and_get_by_provider_and_id(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    oauth_repo = OAuthAccountRepository(db_session)

    created = await oauth_repo.create(
        user_id=user.id,
        provider="google",
        provider_user_id="google-sub-123",
        provider_email="g@example.com",
    )
    await db_session.commit()
    assert created.id is not None

    found = await oauth_repo.get_by_provider_and_id("google", "google-sub-123")
    assert found is not None
    assert found.user_id == user.id
    assert found.provider_email == "g@example.com"


@pytest.mark.asyncio
async def test_get_by_provider_and_id_missing(
    db_session: AsyncSession,
) -> None:
    oauth_repo = OAuthAccountRepository(db_session)
    assert await oauth_repo.get_by_provider_and_id("google", "nope") is None


@pytest.mark.asyncio
async def test_list_for_user_returns_all_links(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    oauth_repo = OAuthAccountRepository(db_session)

    await oauth_repo.create(
        user_id=user.id,
        provider="google",
        provider_user_id="g1",
        provider_email=None,
    )
    await oauth_repo.create(
        user_id=user.id,
        provider="apple",
        provider_user_id="a1",
        provider_email=None,
    )
    await db_session.commit()

    accounts = await oauth_repo.list_for_user(user.id)
    providers = {a.provider for a in accounts}
    assert providers == {"google", "apple"}


@pytest.mark.asyncio
async def test_unique_constraint_on_provider_and_provider_user_id(
    db_session: AsyncSession,
) -> None:
    """Two MAISYS users cannot link to the same external (provider, sub).

    The IntegrityError fires inside ``create()`` at the implicit
    ``flush()`` — we don't wait until ``commit()`` to detect it.
    """
    user_a = await _make_user(db_session, "a@example.com")
    user_b = await _make_user(db_session, "b@example.com")
    oauth_repo = OAuthAccountRepository(db_session)

    await oauth_repo.create(
        user_id=user_a.id,
        provider="google",
        provider_user_id="shared-sub",
        provider_email=None,
    )
    await db_session.commit()

    # Same (provider, provider_user_id) for a different user must fail
    # at flush time (inside create()).
    with pytest.raises(IntegrityError):
        await oauth_repo.create(
            user_id=user_b.id,
            provider="google",
            provider_user_id="shared-sub",
            provider_email=None,
        )
