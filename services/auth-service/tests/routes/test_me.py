"""Tests for GET /auth/me  +  PATCH /auth/me."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository import OTPRepository, UserRepository
from routes.me import router
from tests.routes.conftest import auth_headers


@pytest.mark.asyncio
async def test_get_me_requires_bearer(db_session: AsyncSession, make_client) -> None:
    async with make_client(router) as client:
        response = await client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_returns_profile(db_session: AsyncSession, make_client, verified_user) -> None:
    async with make_client(router) as client:
        response = await client.get("/auth/me", headers=auth_headers(verified_user))
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["email"] == "verified@example.com"
    assert body["data"]["email_verified"] is True


@pytest.mark.asyncio
async def test_patch_me_updates_display_name(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    async with make_client(router) as client:
        response = await client.patch(
            "/auth/me",
            headers=auth_headers(verified_user),
            json={"display_name": "Updated Name"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["user"]["display_name"] == "Updated Name"
    assert body["data"]["email_reverification_required"] is False


@pytest.mark.asyncio
async def test_patch_me_email_change_triggers_reverification(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    async with make_client(router) as client:
        response = await client.patch(
            "/auth/me",
            headers=auth_headers(verified_user),
            json={"email": "shiny@example.com"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["email_reverification_required"] is True
    assert body["data"]["user"]["email"] == "shiny@example.com"
    assert body["data"]["user"]["email_verified"] is False
    # New OTP issued
    otps = OTPRepository(db_session)
    pending = await otps.get_active(verified_user.id, "email_verify")
    assert pending is not None


@pytest.mark.asyncio
async def test_patch_me_email_collision_returns_409(
    db_session: AsyncSession, make_client, verified_user
) -> None:
    users = UserRepository(db_session)
    await users.create(email="taken@example.com", password_hash="h")
    await db_session.commit()
    async with make_client(router) as client:
        response = await client.patch(
            "/auth/me",
            headers=auth_headers(verified_user),
            json={"email": "taken@example.com"},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
