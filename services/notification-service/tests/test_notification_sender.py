"""Tests for ``NotificationSender`` — happy path + retry + failure."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.notification_service.models.schemas import SendNotificationRequest
from services.notification_service.repository.notification_repo import (
    NotificationRepository,
)
from services.notification_service.services.email_adapter import FakeEmailAdapter
from services.notification_service.services.notification_sender import (
    NotificationSender,
)


def _good_request() -> SendNotificationRequest:
    return SendNotificationRequest(
        notification_type="email_verify",
        user_id="user-1",
        recipient_email="ahmad@example.com",
        language="en",
        template_name="email_verify",
        template_vars={
            "user_name": "Ahmad",
            "otp_code": "847291",
            "expires_in_minutes": 10,
        },
        correlation_id="corr-1",
        priority="high",
    )


@pytest.mark.asyncio
async def test_happy_path_delivers_on_first_attempt(
    sender: NotificationSender,
    fake_email_adapter: FakeEmailAdapter,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    notification_id = await sender.accept(_good_request())
    await sender.wait_for_pending()

    assert fake_email_adapter.attempts == 1
    assert len(fake_email_adapter.sent) == 1
    assert fake_email_adapter.sent[0].recipient == "ahmad@example.com"
    assert "847291" in fake_email_adapter.sent[0].html_body

    async with session_factory() as session:
        row = await NotificationRepository(session).get_by_id(notification_id)
    assert row is not None
    assert row.status == "delivered"
    assert row.attempts == 1
    assert row.delivered_at is not None
    assert row.last_error is None


@pytest.mark.asyncio
async def test_retry_then_succeed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """First two attempts fail; the third (within retry budget) succeeds."""
    adapter = FakeEmailAdapter(fail_first_n=2)
    sender = NotificationSender(
        email_adapter=adapter,
        session_factory=session_factory,
        retry_delays=(0.01, 0.01, 0.01),
    )

    notification_id = await sender.accept(_good_request())
    await sender.wait_for_pending()

    assert adapter.attempts == 3
    assert len(adapter.sent) == 1

    async with session_factory() as session:
        row = await NotificationRepository(session).get_by_id(notification_id)
    assert row is not None
    assert row.status == "delivered"
    assert row.attempts == 3  # tracked by repo.mark_delivering(); 3 successful "in flight" stamps


@pytest.mark.asyncio
async def test_retry_exhausted_marks_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """All four attempts fail; row is marked failed with last_error set."""
    adapter = FakeEmailAdapter(fail_first_n=100)
    sender = NotificationSender(
        email_adapter=adapter,
        session_factory=session_factory,
        retry_delays=(0.01, 0.01, 0.01),
    )

    notification_id = await sender.accept(_good_request())
    await sender.wait_for_pending()

    # retry_delays length is 3 → max 4 attempts total (1 + 3 retries)
    assert adapter.attempts == 4
    assert adapter.sent == []

    async with session_factory() as session:
        row = await NotificationRepository(session).get_by_id(notification_id)
    assert row is not None
    assert row.status == "failed"
    assert row.last_error is not None
    assert "Simulated failure" in row.last_error


@pytest.mark.asyncio
async def test_template_error_marked_failed_immediately(
    session_factory: async_sessionmaker[AsyncSession],
    fake_email_adapter: FakeEmailAdapter,
) -> None:
    """Missing template var = caller bug = no retry, mark failed."""
    sender = NotificationSender(
        email_adapter=fake_email_adapter,
        session_factory=session_factory,
        retry_delays=(0.01,),
    )
    bad = SendNotificationRequest(
        notification_type="email_verify",
        user_id="user-1",
        recipient_email="ahmad@example.com",
        language="en",
        template_name="email_verify",
        template_vars={"user_name": "Ahmad"},  # missing otp_code, expires_in_minutes
        priority="high",
    )

    notification_id = await sender.accept(bad)
    await sender.wait_for_pending()

    # Email adapter was never called — render failed before that
    assert fake_email_adapter.attempts == 0

    async with session_factory() as session:
        row = await NotificationRepository(session).get_by_id(notification_id)
    assert row is not None
    assert row.status == "failed"
    assert row.last_error is not None
    assert "render" in row.last_error.lower()


@pytest.mark.asyncio
async def test_template_name_mismatch_rejected_at_accept(
    sender: NotificationSender,
) -> None:
    """notification_type vs template_name disagreement is a 400 at accept time
    — never reaches the background task."""
    from services.notification_service.exceptions.exceptions import (
        TemplateNameMismatch,
    )

    request = SendNotificationRequest(
        notification_type="email_verify",
        user_id="user-1",
        recipient_email="ahmad@example.com",
        language="en",
        template_name="password_reset",  # MISMATCH
        template_vars={
            "user_name": "Ahmad",
            "otp_code": "111111",
            "expires_in_minutes": 10,
        },
        priority="normal",
    )
    with pytest.raises(TemplateNameMismatch):
        await sender.accept(request)


@pytest.mark.asyncio
async def test_arabic_message_delivered(
    sender: NotificationSender,
    fake_email_adapter: FakeEmailAdapter,
) -> None:
    request = SendNotificationRequest(
        notification_type="login_otp",
        user_id="user-1",
        recipient_email="ahmad@example.com",
        language="ar",
        template_name="login_otp",
        template_vars={"otp_code": "555000", "expires_in_minutes": 5},
        priority="high",
    )
    await sender.accept(request)
    await sender.wait_for_pending()

    assert len(fake_email_adapter.sent) == 1
    msg = fake_email_adapter.sent[0]
    assert "555000" in msg.html_body
    assert "رمز" in msg.subject  # Arabic for "code"
    assert 'dir="rtl"' in msg.html_body
