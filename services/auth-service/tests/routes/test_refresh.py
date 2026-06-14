"""Tests for POST /auth/refresh."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository import SessionRepository
from routes.refresh import router
from utils.tokens import generate_refresh_token, hash_refresh_token


async def _active_refresh(db_session: AsyncSession, user_id, jti: str = "jti-r") -> str:
    raw = generate_refresh_token()
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=user_id,
        jwt_jti=jti,
        refresh_token_hash=hash_refresh_token(raw),
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()
    return raw


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(db_session: AsyncSession, make_client, verified_user) -> None:
    raw = await _active_refresh(db_session, verified_user.id)
    async with make_client(router) as client:
        response = await client.post("/auth/refresh", json={"refresh_token": raw})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["refresh_token"] != raw
    assert "access_token" in body["data"]


@pytest.mark.asyncio
async def test_refresh_unknown_token_returns_401(db_session: AsyncSession, make_client) -> None:
    async with make_client(router) as client:
        response = await client.post("/auth/refresh", json={"refresh_token": "definitely-fake"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_all_sessions(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    raw_a = await _active_refresh(db_session, verified_user.id, jti="r-a")
    raw_b = await _active_refresh(db_session, verified_user.id, jti="r-b")
    async with make_client(router) as client:
        # First rotate — succeeds and revokes A.
        first = await client.post("/auth/refresh", json={"refresh_token": raw_a})
        assert first.status_code == 200
        # Reuse A — must trigger panic revocation
        reuse = await client.post("/auth/refresh", json={"refresh_token": raw_a})
    assert reuse.status_code == 401
    # B should now be revoked too
    sessions = SessionRepository(db_session)
    active = await sessions.list_for_user(verified_user.id, only_active=True)
    raw_b_hash = hash_refresh_token(raw_b)
    assert all(s.refresh_token_hash != raw_b_hash for s in active)
