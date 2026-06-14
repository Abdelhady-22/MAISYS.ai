"""Tests for PasswordResetRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User

from repository.password_reset_repository import PasswordResetRepository
from repository.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "reset@example.com") -> User:
    repo = UserRepository(db_session)
    user = await repo.create(email=email, password_hash="h")
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_create_password_reset(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repo = PasswordResetRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)

    reset = await repo.create(
        user_id=user.id,
        token_hash="sha256-token",
        expires_at=expires,
    )
    assert reset.id is not None
    assert reset.used is False
    assert reset.used_at is None


@pytest.mark.asyncio
async def test_get_by_token_hash(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repo = PasswordResetRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.create(
        user_id=user.id,
        token_hash="findable",
        expires_at=expires,
    )
    await db_session.commit()

    found = await repo.get_by_token_hash("findable")
    assert found is not None
    assert found.user_id == user.id

    assert await repo.get_by_token_hash("not-there") is None


@pytest.mark.asyncio
async def test_mark_used(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repo = PasswordResetRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    reset = await repo.create(
        user_id=user.id,
        token_hash="single-use",
        expires_at=expires,
    )
    await db_session.commit()

    await repo.mark_used(reset.id)
    await db_session.commit()
    fetched = await repo.get_by_token_hash("single-use")
    assert fetched is not None
    assert fetched.used is True
    assert fetched.used_at is not None


@pytest.mark.asyncio
async def test_unique_constraint_on_token_hash(
    db_session: AsyncSession,
) -> None:
    """The token_hash column has a UNIQUE constraint; collisions raise at
    flush() (inside ``create()``)."""
    user = await _make_user(db_session)
    repo = PasswordResetRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)

    await repo.create(user_id=user.id, token_hash="duplicate", expires_at=expires)
    await db_session.commit()

    # Inserting another row with the same hash must fail at flush time.
    with pytest.raises(IntegrityError):
        await repo.create(user_id=user.id, token_hash="duplicate", expires_at=expires)
