"""Tests for TokenService (refresh rotation + logout)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    InvalidRefreshTokenException,
    RefreshTokenExpiredException,
)
from repository import SessionRepository, UserRepository
from services.token_service import TokenService
from utils.password import hash_password
from utils.tokens import generate_refresh_token, hash_refresh_token


async def _make_user_and_session(
    db_session: AsyncSession, *, expires_in_days: int = 30
) -> tuple[str, str]:
    """Create a user + active session; return (refresh_token_raw, jti)."""
    users = UserRepository(db_session)
    user = await users.create(email="t@example.com", password_hash=hash_password("Pass-1A"))
    await users.mark_email_verified(user.id)

    sessions = SessionRepository(db_session)
    refresh_raw = generate_refresh_token()
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user.id,
        jwt_jti="jti-1",
        refresh_token_hash=hash_refresh_token(refresh_raw),
        issued_at=now,
        expires_at=now + timedelta(days=expires_in_days),
    )
    await db_session.commit()
    return refresh_raw, "jti-1"


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(db_session: AsyncSession) -> None:
    old_refresh, _ = await _make_user_and_session(db_session)
    service = TokenService(db_session)
    new = await service.refresh(refresh_token=old_refresh)
    # New tokens are distinct from the old refresh
    assert new.refresh_token != old_refresh
    assert new.access_token.count(".") == 2
    # The OLD refresh is now revoked — second use raises
    with pytest.raises(InvalidRefreshTokenException):
        await service.refresh(refresh_token=old_refresh)


@pytest.mark.asyncio
async def test_refresh_unknown_token_rejected(db_session: AsyncSession) -> None:
    service = TokenService(db_session)
    with pytest.raises(InvalidRefreshTokenException):
        await service.refresh(refresh_token="totally-unknown-token")


@pytest.mark.asyncio
async def test_refresh_expired_rejected(db_session: AsyncSession) -> None:
    # Create a session that's already expired
    users = UserRepository(db_session)
    user = await users.create(email="e@example.com", password_hash=hash_password("Pass-1A"))
    sessions = SessionRepository(db_session)
    refresh_raw = generate_refresh_token()
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user.id,
        jwt_jti="jti-exp",
        refresh_token_hash=hash_refresh_token(refresh_raw),
        issued_at=now - timedelta(days=60),
        expires_at=now - timedelta(days=1),  # past
    )
    await db_session.commit()

    service = TokenService(db_session)
    with pytest.raises(RefreshTokenExpiredException):
        await service.refresh(refresh_token=refresh_raw)


@pytest.mark.asyncio
async def test_refresh_reuse_of_revoked_token_revokes_all(
    db_session: AsyncSession,
) -> None:
    """Defence-in-depth: reusing a revoked refresh revokes ALL sessions."""
    refresh_a, _ = await _make_user_and_session(db_session)
    users = UserRepository(db_session)
    user = await users.get_by_email("t@example.com")
    assert user is not None
    sessions = SessionRepository(db_session)

    # Add a second active session
    refresh_b = generate_refresh_token()
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user.id,
        jwt_jti="jti-b",
        refresh_token_hash=hash_refresh_token(refresh_b),
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()

    service = TokenService(db_session)
    # Rotate A — this revokes A.
    await service.refresh(refresh_token=refresh_a)
    # Now reuse A — must trigger panic revocation of B as well.
    with pytest.raises(InvalidRefreshTokenException):
        await service.refresh(refresh_token=refresh_a)
    # B should now be revoked too
    active = await sessions.list_for_user(user.id, only_active=True)
    refresh_b_hash = hash_refresh_token(refresh_b)
    assert all(s.refresh_token_hash != refresh_b_hash for s in active)


@pytest.mark.asyncio
async def test_logout_revokes_session(db_session: AsyncSession) -> None:
    _, jti = await _make_user_and_session(db_session)
    service = TokenService(db_session)
    await service.logout(jwt_jti=jti)

    sessions = SessionRepository(db_session)
    s = await sessions.get_by_jti(jti)
    assert s is not None
    assert s.revoked is True


@pytest.mark.asyncio
async def test_logout_unknown_jti_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """Logging out an unknown jti is a no-op, no exception."""
    service = TokenService(db_session)
    await service.logout(jwt_jti="nonexistent-jti")  # must not raise
