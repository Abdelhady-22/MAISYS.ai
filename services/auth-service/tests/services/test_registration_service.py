"""Tests for RegistrationService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    EmailAlreadyExistsException,
    OTPExpiredException,
    OTPInvalidException,
    OTPMaxAttemptsException,
)
from repository import OTPRepository, UserRepository
from services.registration_service import RegistrationService
from utils.otp import hash_otp


@pytest.mark.asyncio
async def test_register_creates_user_with_unverified_email(
    db_session: AsyncSession,
) -> None:
    service = RegistrationService(db_session)
    user_id = await service.register(
        email="newbie@example.com",
        password="StrongPass1",
        language_preference="en",
    )
    users = UserRepository(db_session)
    user = await users.get_by_id(user_id)
    assert user is not None
    assert user.email == "newbie@example.com"
    assert user.email_verified is False
    assert user.password_hash is not None
    assert user.password_hash != "StrongPass1"  # actually hashed
    # An OTP was created
    otps = OTPRepository(db_session)
    active = await otps.get_active(user_id, "email_verify")
    assert active is not None


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(
    db_session: AsyncSession,
) -> None:
    service = RegistrationService(db_session)
    await service.register(email="dup@example.com", password="StrongPass1")
    with pytest.raises(EmailAlreadyExistsException) as exc_info:
        await service.register(email="dup@example.com", password="StrongPass2")
    assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_verify_email_success(db_session: AsyncSession) -> None:
    """Insert a known OTP and verify it succeeds."""
    users = UserRepository(db_session)
    user = await users.create(email="v@example.com", password_hash="h")
    await db_session.commit()

    otps = OTPRepository(db_session)
    await otps.create(
        user_id=user.id,
        code_hash=hash_otp("123456"),
        purpose="email_verify",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    await db_session.commit()

    service = RegistrationService(db_session)
    await service.verify_email(user_id=user.id, code="123456")

    refreshed = await users.get_by_id(user.id)
    assert refreshed is not None
    assert refreshed.email_verified is True


@pytest.mark.asyncio
async def test_verify_email_no_active_otp(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="noa@example.com", password_hash="h")
    await db_session.commit()

    service = RegistrationService(db_session)
    with pytest.raises(OTPExpiredException):
        await service.verify_email(user_id=user.id, code="123456")


@pytest.mark.asyncio
async def test_verify_email_wrong_code_increments_attempt(
    db_session: AsyncSession,
) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="w@example.com", password_hash="h")
    await db_session.commit()
    otps = OTPRepository(db_session)
    await otps.create(
        user_id=user.id,
        code_hash=hash_otp("111111"),
        purpose="email_verify",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    await db_session.commit()

    service = RegistrationService(db_session)
    # First wrong attempt
    with pytest.raises(OTPInvalidException):
        await service.verify_email(user_id=user.id, code="222222")
    # Second wrong attempt
    with pytest.raises(OTPInvalidException):
        await service.verify_email(user_id=user.id, code="333333")
    # Third wrong attempt → max attempts exception, OTP invalidated
    with pytest.raises(OTPMaxAttemptsException):
        await service.verify_email(user_id=user.id, code="444444")
    # After max-attempts, the OTP is marked used so a new submission
    # reports "expired" (no active OTP).
    with pytest.raises(OTPExpiredException):
        await service.verify_email(user_id=user.id, code="111111")
