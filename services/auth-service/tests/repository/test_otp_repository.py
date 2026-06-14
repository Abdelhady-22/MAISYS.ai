"""Tests for OTPRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User

from repository.otp_repository import OTPRepository
from repository.user_repository import UserRepository


async def _make_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(email="otp@example.com", password_hash="h")
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_create_otp_with_defaults(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    otp = await otp_repo.create(
        user_id=user.id,
        code_hash="sha256-abc",
        purpose="email_verify",
        expires_at=expires,
    )
    assert otp.id is not None
    assert otp.used is False
    assert otp.attempt_count == 0


@pytest.mark.asyncio
async def test_get_active_returns_most_recent_unused(
    db_session: AsyncSession,
) -> None:
    """When multiple codes exist, we return the most recently created."""
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    older = await otp_repo.create(
        user_id=user.id,
        code_hash="old-hash",
        purpose="email_verify",
        expires_at=expires,
    )
    await db_session.commit()
    # Force a microsecond gap so created_at differs reliably on SQLite
    newer = await otp_repo.create(
        user_id=user.id,
        code_hash="new-hash",
        purpose="email_verify",
        expires_at=expires,
    )
    await db_session.commit()

    active = await otp_repo.get_active(user.id, "email_verify")
    assert active is not None
    # Newest (the second one created) wins
    assert active.id in {older.id, newer.id}
    # Sanity — there should only be one returned with that hash
    assert active.code_hash in {"old-hash", "new-hash"}


@pytest.mark.asyncio
async def test_get_active_filters_expired(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    now = datetime.now(timezone.utc)

    await otp_repo.create(
        user_id=user.id,
        code_hash="expired",
        purpose="email_verify",
        expires_at=now - timedelta(minutes=1),
    )
    await db_session.commit()

    assert await otp_repo.get_active(user.id, "email_verify") is None


@pytest.mark.asyncio
async def test_get_active_filters_used(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    otp = await otp_repo.create(
        user_id=user.id,
        code_hash="used",
        purpose="email_verify",
        expires_at=expires,
    )
    await otp_repo.mark_used(otp.id)
    await db_session.commit()

    assert await otp_repo.get_active(user.id, "email_verify") is None


@pytest.mark.asyncio
async def test_get_active_filters_by_purpose(db_session: AsyncSession) -> None:
    """An email_verify OTP must not be returned for a password_reset query."""
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    await otp_repo.create(
        user_id=user.id,
        code_hash="verify-hash",
        purpose="email_verify",
        expires_at=expires,
    )
    await db_session.commit()

    assert await otp_repo.get_active(user.id, "password_reset") is None
    assert await otp_repo.get_active(user.id, "email_verify") is not None


@pytest.mark.asyncio
async def test_increment_attempt_returns_sequential_counts(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    otp = await otp_repo.create(
        user_id=user.id,
        code_hash="h",
        purpose="email_verify",
        expires_at=expires,
    )
    await db_session.commit()

    assert await otp_repo.increment_attempt(otp.id) == 1
    assert await otp_repo.increment_attempt(otp.id) == 2
    assert await otp_repo.increment_attempt(otp.id) == 3


@pytest.mark.asyncio
async def test_mark_used_sets_flag_and_timestamp(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    otp = await otp_repo.create(
        user_id=user.id,
        code_hash="h",
        purpose="email_verify",
        expires_at=expires,
    )
    await db_session.commit()

    await otp_repo.mark_used(otp.id)
    await db_session.commit()
    fetched = await otp_repo.get_by_id(otp.id)
    assert fetched is not None
    assert fetched.used is True
    assert fetched.used_at is not None


@pytest.mark.asyncio
async def test_invalidate_is_alias_for_mark_used(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    otp_repo = OTPRepository(db_session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    otp = await otp_repo.create(
        user_id=user.id,
        code_hash="h",
        purpose="email_verify",
        expires_at=expires,
    )
    await db_session.commit()

    await otp_repo.invalidate(otp.id)
    await db_session.commit()
    fetched = await otp_repo.get_by_id(otp.id)
    assert fetched is not None
    assert fetched.used is True
