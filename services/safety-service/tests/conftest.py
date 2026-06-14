"""Shared pytest fixtures for safety-service tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.safety_service.main import SafetyServiceConfig, create_app
from shared.auth import Role, TokenPayload


@pytest.fixture
def test_config() -> SafetyServiceConfig:
    """Test config — Stage 2 LLM disabled, no metrics."""
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    return SafetyServiceConfig(
        app_env="test",
        log_level="WARNING",
        cors_origins=["*"],
        enable_metrics=False,
        stage_2_llm_enabled=False,
        stage_2_llm_model="fake-model",
        stage_2_llm_timeout_seconds=1.0,
    )


@pytest.fixture
def fake_user() -> TokenPayload:
    """Stand-in JWT payload for routes that require auth."""
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
async def client(
    test_config: SafetyServiceConfig, fake_user: TokenPayload
) -> AsyncIterator[AsyncClient]:
    """An ASGI test client with the auth dependency overridden.

    We override ``get_current_user`` so route tests can focus on
    behaviour without manufacturing real JWTs. A separate test
    explicitly exercises the auth path with a real (test-key) token.

    ASGITransport doesn't run the lifespan by default, so we wire
    the in-memory services directly onto ``app.state`` after
    construction.
    """
    from shared.auth import get_current_user

    from services.safety_service.services.disclaimer_injector import DisclaimerInjector
    from services.safety_service.services.emergency_detector import EmergencyDetector

    app = create_app(test_config)
    app.state.emergency_detector = EmergencyDetector(stage_2_enabled=False)
    app.state.disclaimer_injector = DisclaimerInjector()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
