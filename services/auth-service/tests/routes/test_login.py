"""Tests for POST /auth/login."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository import UserRepository
from routes.login import router
from utils.password import hash_password


@pytest.mark.asyncio
async def test_login_happy_path_returns_tokens(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "verified@example.com",
                "password": "TestP@ssw0rd1",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body["data"]
    assert "refresh_token" in body["data"]
    assert body["data"]["user"]["email"] == "verified@example.com"


@pytest.mark.asyncio
async def test_login_wrong_credentials_returns_401(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "verified@example.com",
                "password": "WrongPassword1",
            },
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(db_session: AsyncSession, make_client) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "Whatever1"},
        )
    assert response.status_code == 401
    # Same code as bad password — no enumeration
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unverified_email_returns_403(db_session: AsyncSession, make_client) -> None:
    users = UserRepository(db_session)
    await users.create(
        email="unv@example.com",
        password_hash=hash_password("TestP@ss1"),
    )
    await db_session.commit()
    async with make_client(router) as client:
        response = await client.post(
            "/auth/login",
            json={"email": "unv@example.com", "password": "TestP@ss1"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_login_otp_gate_returns_otp_required(
    db_session: AsyncSession,
    make_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGIN_OTP_REQUIRED_ROLES", "admin")
    users = UserRepository(db_session)
    user = await users.create(
        email="adm@example.com",
        password_hash=hash_password("AdminP@ss1"),
        role="admin",
    )
    await users.mark_email_verified(user.id)
    await db_session.commit()
    async with make_client(router) as client:
        response = await client.post(
            "/auth/login",
            json={"email": "adm@example.com", "password": "AdminP@ss1"},
        )
    assert response.status_code == 200
    body = response.json()
    # OTP-required shape: has otp_token, no access_token
    assert "otp_token" in body["data"]
    assert "access_token" not in body["data"]
