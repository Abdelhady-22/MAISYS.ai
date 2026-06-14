"""Shared pytest fixtures for notification-service tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.notification_service.main import (
    NotificationServiceConfig,
    create_app,
)
from services.notification_service.models.db import Base
from services.notification_service.services.email_adapter import FakeEmailAdapter
from services.notification_service.services.notification_sender import (
    NotificationSender,
)
from shared.auth import Role, TokenPayload


@pytest.fixture
def test_config() -> NotificationServiceConfig:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    return NotificationServiceConfig(
        app_env="test",
        log_level="WARNING",
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=["*"],
        enable_metrics=False,
        enable_wiring=False,
    )


@pytest.fixture
def fake_user() -> TokenPayload:
    return TokenPayload(
        sub="test-user",
        role=Role.USER,
        exp=9999999999,
        iat=0,
        iss="maisys",
        jti="test-jti",
        scope=[],
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """One in-memory SQLite per test — isolation by default."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def fake_email_adapter() -> FakeEmailAdapter:
    return FakeEmailAdapter()


@pytest_asyncio.fixture
async def sender(
    fake_email_adapter: FakeEmailAdapter,
    session_factory: async_sessionmaker[AsyncSession],
) -> NotificationSender:
    """Sender with fast retry delays so retry tests finish in ms."""
    return NotificationSender(
        email_adapter=fake_email_adapter,
        session_factory=session_factory,
        retry_delays=(0.01, 0.02, 0.05),
    )


@pytest_asyncio.fixture
async def client(
    test_config: NotificationServiceConfig,
    fake_user: TokenPayload,
    fake_email_adapter: FakeEmailAdapter,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """ASGI test client with services wired and auth overridden."""
    from shared.auth import get_current_user

    app = create_app(test_config)
    app.state.session_factory = session_factory
    app.state.email_adapter = fake_email_adapter
    app.state.notification_sender = NotificationSender(
        email_adapter=fake_email_adapter,
        session_factory=session_factory,
        retry_delays=(0.01, 0.02, 0.05),
    )
    app.dependency_overrides[get_current_user] = lambda: fake_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
