"""Tests for POST /auth/verify-otp (purpose dispatcher)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository import OTPRepository, UserRepository
from routes.verify_otp import router
from utils.otp import hash_otp


async def _user_with_otp(
    db_session: AsyncSession, *, code: str, purpose: str
) -> "User":  # noqa: F821
    users = UserRepository(db_session)
    user = await users.create(email="vo@example.com", password_hash="h")
    otps = OTPRepository(db_session)
    await otps.create(
        user_id=user.id,
        code_hash=hash_otp(code),
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_verify_otp_email_verify_success(db_session: AsyncSession, make_client) -> None:
    user = await _user_with_otp(db_session, code="654321", purpose="email_verify")
    async with make_client(router) as client:
        response = await client.post(
            "/auth/verify-otp",
            json={
                "user_id": str(user.id),
                "code": "654321",
                "purpose": "email_verify",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["verified"] is True
    # User now marked email_verified
    users = UserRepository(db_session)
    refreshed = await users.get_by_id(user.id)
    assert refreshed is not None and refreshed.email_verified is True


@pytest.mark.asyncio
async def test_verify_otp_email_verify_wrong_code(db_session: AsyncSession, make_client) -> None:
    user = await _user_with_otp(db_session, code="111111", purpose="email_verify")
    async with make_client(router) as client:
        response = await client.post(
            "/auth/verify-otp",
            json={
                "user_id": str(user.id),
                "code": "999999",
                "purpose": "email_verify",
            },
        )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "OTP_INVALID"


@pytest.mark.asyncio
async def test_verify_otp_password_reset_purpose_rejected(
    db_session: AsyncSession, make_client
) -> None:
    """purpose=password_reset belongs at /auth/password/reset/confirm."""
    user = await _user_with_otp(db_session, code="123456", purpose="email_verify")
    async with make_client(router) as client:
        response = await client.post(
            "/auth/verify-otp",
            json={
                "user_id": str(user.id),
                "code": "123456",
                "purpose": "password_reset",
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OTP_INVALID"
