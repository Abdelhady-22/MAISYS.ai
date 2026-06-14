"""Tests for ProfileService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    EmailAlreadyExistsException,
    SessionNotFoundException,
)
from repository import SessionRepository, UserRepository
from services.profile_service import ProfileService
from utils.password import hash_password


async def _verified_user(
    db_session: AsyncSession, email: str = "p@example.com"
) -> "User":  # noqa: F821
    users = UserRepository(db_session)
    user = await users.create(
        email=email,
        password_hash=hash_password("Pass-1A"),
        display_name="Profile User",
    )
    await users.mark_email_verified(user.id)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_get_me_returns_profile_with_display_name(
    db_session: AsyncSession,
) -> None:
    user = await _verified_user(db_session)
    service = ProfileService(db_session)
    snapshot = await service.get_me(user.id)
    assert snapshot.user.id == user.id
    assert snapshot.display_name == "Profile User"


@pytest.mark.asyncio
async def test_update_profile_patches_only_provided_fields(
    db_session: AsyncSession,
) -> None:
    user = await _verified_user(db_session)
    service = ProfileService(db_session)
    result = await service.update_profile(user_id=user.id, display_name="New Name")
    assert result.snapshot.display_name == "New Name"
    assert result.email_reverification_required is False
    # Language unchanged
    assert result.snapshot.user.language_preference == "en"


@pytest.mark.asyncio
async def test_update_profile_email_triggers_reverification(
    db_session: AsyncSession,
) -> None:
    user = await _verified_user(db_session, email="old@example.com")
    service = ProfileService(db_session)
    result = await service.update_profile(user_id=user.id, email="new@example.com")
    assert result.email_reverification_required is True
    assert result.snapshot.user.email == "new@example.com"
    # Email-verified flag cleared
    assert result.snapshot.user.email_verified is False


@pytest.mark.asyncio
async def test_update_profile_email_collision_rejected(
    db_session: AsyncSession,
) -> None:
    await _verified_user(db_session, email="taken@example.com")
    user_b = await _verified_user(db_session, email="b@example.com")
    service = ProfileService(db_session)
    with pytest.raises(EmailAlreadyExistsException):
        await service.update_profile(user_id=user_b.id, email="taken@example.com")


@pytest.mark.asyncio
async def test_list_sessions_only_active(db_session: AsyncSession) -> None:
    user = await _verified_user(db_session)
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    active = await sessions.create(
        user_id=user.id,
        jwt_jti="active-1",
        refresh_token_hash="hash-1",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    revoked = await sessions.create(
        user_id=user.id,
        jwt_jti="revoked-1",
        refresh_token_hash="hash-2",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await sessions.revoke(revoked.id)
    await db_session.commit()

    service = ProfileService(db_session)
    listed = await service.list_sessions(user.id)
    assert [s.id for s in listed] == [active.id]


@pytest.mark.asyncio
async def test_revoke_session_belongs_to_other_user_not_found(
    db_session: AsyncSession,
) -> None:
    """A user cannot revoke another user's session — same error code as
    'doesn't exist' to avoid leaking session ownership."""
    user_a = await _verified_user(db_session, email="a@example.com")
    user_b = await _verified_user(db_session, email="bb@example.com")
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    b_session = await sessions.create(
        user_id=user_b.id,
        jwt_jti="b-jti",
        refresh_token_hash="b-hash",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()

    service = ProfileService(db_session)
    # User A tries to revoke User B's session
    with pytest.raises(SessionNotFoundException):
        await service.revoke_session(user_id=user_a.id, session_id=b_session.id)


@pytest.mark.asyncio
async def test_revoke_session_own_succeeds(db_session: AsyncSession) -> None:
    user = await _verified_user(db_session)
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    s = await sessions.create(
        user_id=user.id,
        jwt_jti="mine",
        refresh_token_hash="mine-hash",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()

    service = ProfileService(db_session)
    await service.revoke_session(user_id=user.id, session_id=s.id)
    refreshed = await sessions.get_by_id(s.id)
    assert refreshed is not None
    assert refreshed.revoked is True
