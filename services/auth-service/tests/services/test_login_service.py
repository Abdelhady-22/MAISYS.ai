"""Tests for LoginService."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    AccountDeactivatedException,
    AccountLockedException,
    EmailNotVerifiedException,
    InvalidCredentialsException,
)
from repository import UserRepository
from services.login_service import LoginOTPRequired, LoginService, LoginTokens
from utils.password import hash_password


async def _user(
    db_session: AsyncSession,
    *,
    email: str = "u@example.com",
    password: str = "TestP@ss1",
    role: str = "user",
    email_verified: bool = True,
    is_active: bool = True,
) -> str:
    users = UserRepository(db_session)
    user = await users.create(
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    if email_verified:
        await users.mark_email_verified(user.id)
    if not is_active:
        # We don't have a deactivate helper; flip is_active directly.
        user.is_active = False
    await db_session.commit()
    await db_session.refresh(user)
    return user.email


@pytest.mark.asyncio
async def test_login_happy_path(db_session: AsyncSession) -> None:
    await _user(db_session, email="ok@example.com")
    service = LoginService(db_session)
    result = await service.login(email="ok@example.com", password="TestP@ss1")
    assert isinstance(result, LoginTokens)
    assert result.access_token.count(".") == 2
    assert len(result.refresh_token) == 43


@pytest.mark.asyncio
async def test_login_wrong_password_increments_counter(
    db_session: AsyncSession,
) -> None:
    await _user(db_session, email="bad@example.com")
    service = LoginService(db_session)
    with pytest.raises(InvalidCredentialsException):
        await service.login(email="bad@example.com", password="WrongPass1")
    users = UserRepository(db_session)
    user = await users.get_by_email("bad@example.com")
    assert user is not None
    assert user.failed_login_attempts == 1


@pytest.mark.asyncio
async def test_login_locks_after_five_attempts(
    db_session: AsyncSession,
) -> None:
    """The 5th wrong password locks the account; the 6th attempt raises
    AccountLockedException."""
    await _user(db_session, email="lock@example.com")
    service = LoginService(db_session)
    for _ in range(4):
        with pytest.raises(InvalidCredentialsException):
            await service.login(email="lock@example.com", password="WrongPass1")
    # 5th attempt locks the account → AccountLockedException
    with pytest.raises(AccountLockedException):
        await service.login(email="lock@example.com", password="WrongPass1")
    # 6th attempt: account is already locked
    with pytest.raises(AccountLockedException):
        await service.login(email="lock@example.com", password="TestP@ss1")


@pytest.mark.asyncio
async def test_login_unknown_email_returns_invalid_credentials(
    db_session: AsyncSession,
) -> None:
    """Same code as bad password — prevents email enumeration."""
    service = LoginService(db_session)
    with pytest.raises(InvalidCredentialsException):
        await service.login(email="ghost@example.com", password="any")


@pytest.mark.asyncio
async def test_login_unverified_email_blocked(db_session: AsyncSession) -> None:
    await _user(db_session, email="un@example.com", email_verified=False)
    service = LoginService(db_session)
    with pytest.raises(EmailNotVerifiedException):
        await service.login(email="un@example.com", password="TestP@ss1")


@pytest.mark.asyncio
async def test_login_deactivated_blocked(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="x@example.com", password_hash=hash_password("TestP@ss1"))
    await users.mark_email_verified(user.id)
    user.is_active = False
    await db_session.commit()

    service = LoginService(db_session)
    with pytest.raises(AccountDeactivatedException):
        await service.login(email="x@example.com", password="TestP@ss1")


@pytest.mark.asyncio
async def test_login_admin_role_triggers_otp_gate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the user's role is in LOGIN_OTP_REQUIRED_ROLES, login returns
    an OTP-required response instead of tokens."""
    monkeypatch.setenv("LOGIN_OTP_REQUIRED_ROLES", "admin,super_admin")
    await _user(db_session, email="a@example.com", role="admin")
    service = LoginService(db_session)
    result = await service.login(email="a@example.com", password="TestP@ss1")
    assert isinstance(result, LoginOTPRequired)


@pytest.mark.asyncio
async def test_complete_otp_login_issues_tokens(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """complete_otp_login (called after a successful OTP verify) issues
    a fresh token pair for the named user."""
    monkeypatch.setenv("LOGIN_OTP_REQUIRED_ROLES", "admin")
    email = await _user(db_session, email="ad@example.com", role="admin")
    users = UserRepository(db_session)
    user = await users.get_by_email(email)
    assert user is not None

    service = LoginService(db_session)
    result = await service.complete_otp_login(user_id=user.id)
    assert isinstance(result, LoginTokens)
    assert result.user.id == user.id
