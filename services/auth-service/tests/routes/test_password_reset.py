"""Tests for /auth/password/reset/request and /confirm."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import PasswordReset
from repository import PasswordResetRepository, UserRepository
from routes.password_reset import router
from utils.password import hash_password, verify_password
from utils.tokens import generate_refresh_token, hash_refresh_token


@pytest.mark.asyncio
async def test_request_with_known_email_returns_generic_200(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/password/reset/request",
            json={"email": "verified@example.com"},
        )
    assert response.status_code == 200
    # Token row created
    result = await db_session.execute(
        select(PasswordReset).where(PasswordReset.user_id == verified_user.id)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_request_with_unknown_email_also_200(db_session: AsyncSession, make_client) -> None:
    """No email enumeration — same 200 response regardless of lookup."""
    async with make_client(router) as client:
        response = await client.post(
            "/auth/password/reset/request",
            json={"email": "nobody@example.com"},
        )
    assert response.status_code == 200
    # No row created
    result = await db_session.execute(select(PasswordReset))
    assert list(result.scalars().all()) == []


@pytest.mark.asyncio
async def test_confirm_with_valid_token_updates_password(
    db_session: AsyncSession, make_client
) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="cf@example.com", password_hash=hash_password("Old-1A"))
    raw = generate_refresh_token()
    resets = PasswordResetRepository(db_session)
    await resets.create(
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    await db_session.commit()

    async with make_client(router) as client:
        response = await client.post(
            "/auth/password/reset/confirm",
            json={"token": raw, "new_password": "NewP@ssw0rd1"},
        )
    assert response.status_code == 200
    refreshed = await users.get_by_id(user.id)
    assert refreshed is not None and refreshed.password_hash is not None
    assert verify_password(refreshed.password_hash, "NewP@ssw0rd1") is True


@pytest.mark.asyncio
async def test_confirm_with_expired_token_returns_422(
    db_session: AsyncSession, make_client
) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="ex@example.com", password_hash=hash_password("Old-1A"))
    raw = generate_refresh_token()
    resets = PasswordResetRepository(db_session)
    await resets.create(
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await db_session.commit()

    async with make_client(router) as client:
        response = await client.post(
            "/auth/password/reset/confirm",
            json={"token": raw, "new_password": "NewP@ssw0rd1"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PASSWORD_FORMAT"
