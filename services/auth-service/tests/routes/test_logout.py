"""Tests for POST /auth/logout."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository import SessionRepository
from routes.logout import router
from tests.routes.conftest import auth_headers
from utils.jwt import issue_access_token
from shared.auth import Role


@pytest.mark.asyncio
async def test_logout_with_bearer_revokes_session(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    # Create a session with a known JTI, then issue a token whose JTI
    # matches it — the route uses the JTI in the JWT to find which
    # session to revoke.
    token, jti = issue_access_token(str(verified_user.id), Role(verified_user.role))
    sessions = SessionRepository(db_session)
    now = datetime.now(timezone.utc)
    await sessions.create(
        user_id=verified_user.id,
        jwt_jti=jti,
        refresh_token_hash="some-hash",
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )
    await db_session.commit()

    async with make_client(router) as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    # Session now revoked
    s = await sessions.get_by_jti(jti)
    assert s is not None and s.revoked is True


@pytest.mark.asyncio
async def test_logout_missing_auth_returns_401(db_session: AsyncSession, make_client) -> None:
    async with make_client(router) as client:
        response = await client.post("/auth/logout")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_is_idempotent_for_unknown_jti(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    """Even if the JTI in the token doesn't match any session row,
    logout succeeds (no info leak)."""
    headers = auth_headers(verified_user)
    async with make_client(router) as client:
        response = await client.post("/auth/logout", headers=headers)
    # The session for this token was never persisted, but logout
    # returns 200 anyway.
    assert response.status_code == 200
