"""Tests for SessionRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User

from repository.session_repository import SessionRepository
from repository.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "user@example.com") -> User:
    """Helper — create a user we can attach sessions to."""
    repo = UserRepository(db_session)
    user = await repo.create(email=email, password_hash="h")
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_create_session(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sessions = SessionRepository(db_session)

    now = datetime.now(timezone.utc)
    s = await sessions.create(
        user_id=user.id,
        jwt_jti="jti-abc",
        refresh_token_hash="hash-xyz",
        issued_at=now,
        expires_at=now + timedelta(days=30),
        user_agent="pytest",
        ip_address="127.0.0.1",
    )
    assert s.id is not None
    assert s.revoked is False
    assert s.user_agent == "pytest"


@pytest.mark.asyncio
async def test_get_by_jti(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user.id,
        jwt_jti="findable-jti",
        refresh_token_hash="h1",
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    await db_session.commit()

    found = await sessions.get_by_jti("findable-jti")
    assert found is not None
    assert found.user_id == user.id

    assert await sessions.get_by_jti("missing") is None


@pytest.mark.asyncio
async def test_get_by_refresh_hash(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user.id,
        jwt_jti="jti2",
        refresh_token_hash="refresh-hash-zzz",
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    await db_session.commit()

    found = await sessions.get_by_refresh_hash("refresh-hash-zzz")
    assert found is not None
    assert found.user_id == user.id


@pytest.mark.asyncio
async def test_revoke_idempotent(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    s = await sessions.create(
        user_id=user.id,
        jwt_jti="j3",
        refresh_token_hash="h3",
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    await db_session.commit()

    await sessions.revoke(s.id)
    await db_session.commit()
    fetched = await sessions.get_by_id(s.id)
    assert fetched is not None
    assert fetched.revoked is True
    revoked_at = fetched.revoked_at
    assert revoked_at is not None

    # Second revoke is a no-op — revoked_at must NOT be updated again.
    await sessions.revoke(s.id)
    await db_session.commit()
    fetched_again = await sessions.get_by_id(s.id)
    assert fetched_again is not None
    assert fetched_again.revoked_at == revoked_at


@pytest.mark.asyncio
async def test_list_for_user_only_active(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)

    # Active
    active = await sessions.create(
        user_id=user.id,
        jwt_jti="ja",
        refresh_token_hash="ha",
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    # Revoked
    revoked = await sessions.create(
        user_id=user.id,
        jwt_jti="jr",
        refresh_token_hash="hr",
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    await sessions.revoke(revoked.id)
    # Expired
    await sessions.create(
        user_id=user.id,
        jwt_jti="je",
        refresh_token_hash="he",
        issued_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=1),
    )
    await db_session.commit()

    active_only = await sessions.list_for_user(user.id, only_active=True)
    ids = {s.id for s in active_only}
    assert active.id in ids
    assert revoked.id not in ids
    assert len(active_only) == 1

    all_sessions = await sessions.list_for_user(user.id, only_active=False)
    assert len(all_sessions) == 3


@pytest.mark.asyncio
async def test_list_for_user_ordered_newest_first(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    sessions = SessionRepository(db_session)
    base = datetime.now(timezone.utc)

    s1 = await sessions.create(
        user_id=user.id,
        jwt_jti="t1",
        refresh_token_hash="t1h",
        issued_at=base - timedelta(hours=2),
        expires_at=base + timedelta(days=1),
    )
    s2 = await sessions.create(
        user_id=user.id,
        jwt_jti="t2",
        refresh_token_hash="t2h",
        issued_at=base - timedelta(hours=1),
        expires_at=base + timedelta(days=1),
    )
    s3 = await sessions.create(
        user_id=user.id,
        jwt_jti="t3",
        refresh_token_hash="t3h",
        issued_at=base,
        expires_at=base + timedelta(days=1),
    )
    await db_session.commit()

    listed = await sessions.list_for_user(user.id)
    assert [s.id for s in listed] == [s3.id, s2.id, s1.id]


@pytest.mark.asyncio
async def test_revoke_all_for_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "multi@example.com")
    other = await _make_user(db_session, "other@example.com")
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)

    # Two for our user
    for jti in ("ma", "mb"):
        await sessions.create(
            user_id=user.id,
            jwt_jti=jti,
            refresh_token_hash=f"h-{jti}",
            issued_at=now,
            expires_at=now + timedelta(days=1),
        )
    # One for someone else — must NOT be revoked
    await sessions.create(
        user_id=other.id,
        jwt_jti="other-j",
        refresh_token_hash="other-h",
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    await db_session.commit()

    revoked = await sessions.revoke_all_for_user(user.id)
    await db_session.commit()
    assert revoked == 2

    # Other user's session is untouched.
    other_sess = await sessions.list_for_user(other.id, only_active=True)
    assert len(other_sess) == 1
