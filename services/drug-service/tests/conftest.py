"""drug-service test fixtures.

Each test gets:

* ``app`` — a freshly-built FastAPI app via ``create_app(config)``
  with an in-memory SQLite database.
* ``client`` — an ``httpx.AsyncClient`` that hits the app directly via
  ASGITransport.
* ``auth_headers`` — Authorization header with a valid JWT minted from
  the same secret as the app dependency reads.

The ``get_db_session`` and ``get_current_user`` shared dependencies
are overridden so tests don't need real Postgres or auth-service.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# Ensure the repo root is on sys.path so ``shared.*`` and
# ``services.drug_service.*`` import cleanly under pytest.
_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.drug_service.main import DrugServiceConfig, create_app
from services.drug_service.models.db import Base
from shared.auth import Role, TokenPayload
from shared.models import get_db_session


@pytest_asyncio.fixture
async def db_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """In-memory async SQLite for the duration of one test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def test_config() -> DrugServiceConfig:
    """Use an unreachable DB URL — tests override get_db_session anyway."""
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    return DrugServiceConfig(
        app_env="test",
        log_level="WARNING",
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=["*"],
        enable_metrics=False,
    )


@pytest_asyncio.fixture
async def app(test_config: DrugServiceConfig, db_session_factory):
    """Build a fresh app and override the DB + auth dependencies."""
    fastapi_app = create_app(test_config)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            yield session

    def _override_user() -> TokenPayload:
        return TokenPayload(
            sub="test-user-id",
            role=Role.USER,
            exp=9999999999,
            iat=0,
            iss="maisys",
            jti="test-jti",
            scope=[],
        )

    from shared.auth import get_current_user

    fastapi_app.dependency_overrides[get_db_session] = _override_session
    fastapi_app.dependency_overrides[get_current_user] = _override_user
    yield fastapi_app


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """httpx client that hits the in-process app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Authorisation header for tests that DON'T rely on the user override.

    Most tests use the dependency override above, but a few need a
    real-looking Bearer token to test 401 / 403 paths.
    """
    return {"Authorization": "Bearer dummy-test-token"}
