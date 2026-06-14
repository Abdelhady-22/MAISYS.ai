"""Tests for POST /auth/register."""

from __future__ import annotations

import pytest

from routes.register import router


@pytest.mark.asyncio
async def test_register_returns_201_with_user_id(make_client) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "StrongPass1"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "new@example.com"
    assert "user_id" in body["data"]


@pytest.mark.asyncio
async def test_register_duplicate_returns_409(make_client) -> None:
    async with make_client(router) as client:
        # First registration succeeds
        first = await client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "StrongPass1"},
        )
        assert first.status_code == 201
        # Second with same email rejected
        second = await client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "DifferentPass2"},
        )
    assert second.status_code == 409
    body = second.json()
    assert body["success"] is False
    assert body["error"]["code"] == "EMAIL_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_register_weak_password_returns_422(make_client) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/register",
            json={"email": "weak@example.com", "password": "short"},
        )
    # Pydantic validation runs before our service, so status is 422
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email_returns_422(make_client) -> None:
    async with make_client(router) as client:
        response = await client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "StrongPass1"},
        )
    assert response.status_code == 422
