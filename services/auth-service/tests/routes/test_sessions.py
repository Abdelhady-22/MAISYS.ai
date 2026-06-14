"""Tests for GET /auth/sessions and DELETE /auth/sessions/{id}."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository import SessionRepository, UserRepository
from routes.sessions import router
from tests.routes.conftest import auth_headers


@pytest.mark.asyncio
async def test_list_sessions_requires_bearer(db_session: AsyncSession, make_client) -> None:
    async with make_client(router) as client:
        response = await client.get("/auth/sessions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_sessions_returns_active_only(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    active = await sessions.create(
        user_id=verified_user.id,
        jwt_jti="list-active",
        refresh_token_hash="ha",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    revoked = await sessions.create(
        user_id=verified_user.id,
        jwt_jti="list-revoked",
        refresh_token_hash="hb",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await sessions.revoke(revoked.id)
    await db_session.commit()

    async with make_client(router) as client:
        response = await client.get("/auth/sessions", headers=auth_headers(verified_user))
    assert response.status_code == 200
    body = response.json()
    returned_ids = [s["id"] for s in body["data"]["sessions"]]
    assert str(active.id) in returned_ids
    assert str(revoked.id) not in returned_ids


@pytest.mark.asyncio
async def test_delete_own_session_succeeds(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    s = await sessions.create(
        user_id=verified_user.id,
        jwt_jti="own-1",
        refresh_token_hash="own-h",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()
    async with make_client(router) as client:
        response = await client.delete(
            f"/auth/sessions/{s.id}", headers=auth_headers(verified_user)
        )
    assert response.status_code == 200
    refreshed = await sessions.get_by_id(s.id)
    assert refreshed is not None and refreshed.revoked is True


@pytest.mark.asyncio
async def test_delete_other_users_session_returns_404(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    """A user cannot revoke another user's session — returns SESSION_NOT_FOUND
    same as if it didn't exist."""
    users = UserRepository(db_session)
    other = await users.create(email="other@example.com", password_hash="h")
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    other_session = await sessions.create(
        user_id=other.id,
        jwt_jti="other-jti",
        refresh_token_hash="other-h",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()

    async with make_client(router) as client:
        response = await client.delete(
            f"/auth/sessions/{other_session.id}",
            headers=auth_headers(verified_user),
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_nonexistent_session_returns_404(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    async with make_client(router) as client:
        response = await client.delete(
            f"/auth/sessions/{uuid4()}",
            headers=auth_headers(verified_user),
        )
    assert response.status_code == 404
