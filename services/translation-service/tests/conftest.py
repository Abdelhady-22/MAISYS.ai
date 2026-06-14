"""Shared pytest fixtures for translation-service tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.translation_service.main import (
    TranslationServiceConfig,
    create_app,
)
from services.translation_service.repository.cache_repo import (
    InMemoryTranslationCache,
)
from services.translation_service.services.mode_selector import ModeSelector
from services.translation_service.services.translation_service import (
    TranslationService,
)
from services.translation_service.services.translators.protocol import FakeTranslator
from shared.auth import Role, TokenPayload


@pytest.fixture
def test_config() -> TranslationServiceConfig:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    return TranslationServiceConfig(
        app_env="test",
        log_level="WARNING",
        redis_url=None,
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


@pytest.fixture
def fake_google() -> FakeTranslator:
    return FakeTranslator()


@pytest.fixture
def fake_local() -> FakeTranslator:
    return FakeTranslator()


@pytest.fixture
def fake_llm() -> FakeTranslator:
    return FakeTranslator()


@pytest.fixture
def cache() -> InMemoryTranslationCache:
    return InMemoryTranslationCache()


@pytest.fixture
def mode_selector(
    fake_google: FakeTranslator,
    fake_local: FakeTranslator,
    fake_llm: FakeTranslator,
) -> ModeSelector:
    return ModeSelector(google=fake_google, local=fake_local, llm=fake_llm)


@pytest.fixture
def translation_service(
    mode_selector: ModeSelector,
    cache: InMemoryTranslationCache,
) -> TranslationService:
    return TranslationService(mode_selector=mode_selector, cache=cache)


@pytest_asyncio.fixture
async def client(
    test_config: TranslationServiceConfig,
    fake_user: TokenPayload,
    mode_selector: ModeSelector,
    cache: InMemoryTranslationCache,
    translation_service: TranslationService,
) -> AsyncIterator[AsyncClient]:
    from shared.auth import get_current_user

    app = create_app(test_config)
    app.state.mode_selector = mode_selector
    app.state.cache = cache
    app.state.translation_service = translation_service
    app.dependency_overrides[get_current_user] = lambda: fake_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
