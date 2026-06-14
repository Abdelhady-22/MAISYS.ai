"""Tests for PasswordResetService (request + confirm)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import InvalidPasswordFormatException
from models.db import PasswordReset
from repository import (
    PasswordResetRepository,
    SessionRepository,
    UserRepository,
)
from services.password_reset_service import PasswordResetService
from utils.password import hash_password, verify_password
from utils.tokens import generate_refresh_token, hash_refresh_token


@pytest.mark.asyncio
async def test_request_for_existing_user_creates_reset_row(
    db_session: AsyncSession,
) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="r@example.com", password_hash=hash_password("OldPass1"))
    await db_session.commit()

    service = PasswordResetService(db_session)
    await service.request_reset(email="r@example.com")

    # A password_resets row was created for this user
    result = await db_session.execute(select(PasswordReset).where(PasswordReset.user_id == user.id))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].used is False


@pytest.mark.asyncio
async def test_request_for_unknown_email_silent(
    db_session: AsyncSession,
) -> None:
    """request_reset must NOT raise for unknown emails (no enumeration)."""
    service = PasswordResetService(db_session)
    await service.request_reset(email="ghost@example.com")  # no exception
    # No row was created.
    result = await db_session.execute(select(PasswordReset))
    assert list(result.scalars().all()) == []


@pytest.mark.asyncio
async def test_confirm_updates_password_and_revokes_sessions(
    db_session: AsyncSession,
) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="c@example.com", password_hash=hash_password("OldPass1"))
    # Add an active session to ensure it gets revoked.
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user.id,
        jwt_jti="some-jti",
        refresh_token_hash="some-hash",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )

    # Issue a reset token directly via the repo
    raw_token = generate_refresh_token()
    resets = PasswordResetRepository(db_session)
    await resets.create(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=now + timedelta(minutes=30),
    )
    await db_session.commit()

    service = PasswordResetService(db_session)
    await service.confirm_reset(token=raw_token, new_password="NewP@ssw0rd1")

    # Password has changed
    refreshed = await users.get_by_id(user.id)
    assert refreshed is not None
    assert refreshed.password_hash is not None
    assert verify_password(refreshed.password_hash, "NewP@ssw0rd1") is True
    assert verify_password(refreshed.password_hash, "OldPass1") is False

    # All sessions revoked
    active = await sessions.list_for_user(user.id, only_active=True)
    assert active == []

    # Token marked used — second use rejected
    with pytest.raises(InvalidPasswordFormatException):
        await service.confirm_reset(token=raw_token, new_password="AnotherP1")


@pytest.mark.asyncio
async def test_confirm_with_unknown_token_rejected(
    db_session: AsyncSession,
) -> None:
    service = PasswordResetService(db_session)
    with pytest.raises(InvalidPasswordFormatException):
        await service.confirm_reset(token="totally-fake-token", new_password="NewP@ssw0rd1")


@pytest.mark.asyncio
async def test_confirm_with_expired_token_rejected(
    db_session: AsyncSession,
) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="ex@example.com", password_hash=hash_password("OldPass1"))
    resets = PasswordResetRepository(db_session)
    raw_token = generate_refresh_token()
    await resets.create(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await db_session.commit()

    service = PasswordResetService(db_session)
    with pytest.raises(InvalidPasswordFormatException):
        await service.confirm_reset(token=raw_token, new_password="NewP@ss1")
