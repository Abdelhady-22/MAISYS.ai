"""Tests for AuditRepository."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User

from repository.audit_repository import AuditRepository
from repository.user_repository import UserRepository


async def _make_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(email="audit@example.com", password_hash="h")
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_log_creates_row(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    audit = AuditRepository(db_session)

    record = await audit.log(
        action="user.registered",
        user_id=user.id,
        ip_address="10.0.0.1",
        user_agent="pytest/1.0",
        details={"source": "register-endpoint"},
    )
    await db_session.commit()
    assert record.id is not None
    assert record.created_at is not None
    assert record.details == {"source": "register-endpoint"}


@pytest.mark.asyncio
async def test_log_accepts_null_user_id(db_session: AsyncSession) -> None:
    """Pre-login events (e.g. failed registration) have no user_id yet."""
    audit = AuditRepository(db_session)
    record = await audit.log(
        action="register.duplicate_email",
        user_id=None,
        ip_address="10.0.0.2",
        details={"attempted_email_hash": "abc123"},
    )
    await db_session.commit()
    assert record.user_id is None
    assert record.action == "register.duplicate_email"


@pytest.mark.asyncio
async def test_log_details_roundtrip_through_json_column(
    db_session: AsyncSession,
) -> None:
    """details should round-trip arbitrary JSON-serialisable data."""
    user = await _make_user(db_session)
    audit = AuditRepository(db_session)

    payload: dict[str, object] = {
        "nested": {"key": "value", "n": 42},
        "list": [1, 2, 3],
        "bool": True,
        "null": None,
    }
    await audit.log(action="test.payload", user_id=user.id, details=payload)
    await db_session.commit()

    rows = await audit.list_for_user(user.id)
    assert len(rows) == 1
    assert rows[0].details == payload


@pytest.mark.asyncio
async def test_list_for_user_newest_first_with_limit(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    audit = AuditRepository(db_session)

    # AuditRepository.log() sets created_at in Python (microsecond
    # precision), so successive logs always have strictly increasing
    # timestamps without needing a sleep.
    for i in range(5):
        await audit.log(action=f"a{i}", user_id=user.id)
        await asyncio.sleep(0)  # yield to ensure datetime.now() advances
    await db_session.commit()

    # Newest first
    rows = await audit.list_for_user(user.id)
    actions = [r.action for r in rows]
    # Last logged should be first in the list
    assert actions[0] == "a4"
    assert actions[-1] == "a0"

    # Limit honoured
    rows = await audit.list_for_user(user.id, limit=2)
    assert len(rows) == 2
