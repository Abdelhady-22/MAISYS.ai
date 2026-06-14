"""Integration-test fixtures.

These tests exercise the REAL ``main.py`` application object — same
middleware stack, same exception handlers, same router wiring as
production. We only override the ``get_db_session`` dependency so the
tests run against the in-memory SQLite session already provided by
``tests/conftest.py``.

The module-level env-var setup runs BEFORE pytest imports the test
files, ensuring main.py's module-level singletons (the slowapi
``Limiter``, the CORS config) are constructed with the right values.
"""

from __future__ import annotations

import os

# Disable rate limiting in tests — slowapi would otherwise reject the
# rapid-fire requests an integration test makes.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# Required by main.py at import time. The override below makes this URL
# unused at request time, but it has to be set so lifespan-equivalent
# checks pass.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_integration_test_unused.db")
os.environ.setdefault("JWT_SECRET", "integration-test-secret")
os.environ.setdefault("JWT_ISSUER", "maisys")

from collections.abc import AsyncIterator  # noqa: E402

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


@pytest_asyncio.fixture
async def integration_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Yield a client bound to ``main.app`` with the DB redirected.

    Importing ``main`` is done inside the fixture so the env-var setup
    above takes effect on the FIRST import. Subsequent imports return
    the cached module — and the dependency override is reset on every
    fixture invocation.
    """
    from main import app
    from shared.models import get_db_session

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        # Reset override so subsequent tests start clean.
        app.dependency_overrides.pop(get_db_session, None)
