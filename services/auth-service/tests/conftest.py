"""Shared fixtures for auth-service tests.

The key fixture is :func:`db_session` — it creates an in-memory SQLite
engine per test, runs the Alembic migration head, hands back an
``AsyncSession``, then tears down. This gives each test a clean database
without any shared state.

The engine uses ``StaticPool`` so all sessions in the same test share the
same SQLite connection (in-memory databases are per-connection without
this; the migration would write to one connection and the test would read
an empty database from another).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

if False:  # TYPE_CHECKING guard without importing typing.TYPE_CHECKING repeatedly
    from alembic.config import Config

# Path setup so the service's own modules are importable as top-level
# (matching the layout when the service is installed as a package).
_SERVICE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SERVICE_DIR.parent.parent
sys.path.insert(0, str(_SERVICE_DIR))
sys.path.insert(0, str(_REPO_ROOT))


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite engine. Each test gets a fresh one."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def migrated_engine(engine: AsyncEngine) -> AsyncEngine:
    """Engine with the auth-service Alembic migration applied head-to-head.

    Uses Alembic's Python API (rather than the CLI) so we don't fork a
    subprocess for every test. We invoke ``upgrade`` against the in-memory
    SQLite connection directly.
    """
    from alembic.config import Config

    ini_path = _SERVICE_DIR / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(_SERVICE_DIR / "alembic"))

    # Point Alembic at our in-memory engine via the env var dance.
    async with engine.connect() as conn:
        await conn.run_sync(lambda sync_conn: _run_upgrade(sync_conn, cfg))
    return engine


def _run_upgrade(connection: Connection, cfg: "Config") -> None:
    """Hand Alembic a live sync connection and run upgrade head."""
    from alembic.runtime.environment import EnvironmentContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)

    def upgrade(rev: object, _context: object) -> list[object]:
        return script._upgrade_revs("head", rev)  # type: ignore[arg-type,return-value]

    with EnvironmentContext(
        cfg,
        script,
        fn=upgrade,
        as_sql=False,
        starting_rev=None,
        destination_rev="head",
    ) as env_ctx:
        env_ctx.configure(connection=connection, target_metadata=None)
        with env_ctx.begin_transaction():
            env_ctx.run_migrations()


@pytest_asyncio.fixture
async def db_session(
    migrated_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """One AsyncSession per test against the migrated in-memory DB.

    The session auto-flushes but does NOT auto-commit; tests should call
    ``await session.commit()`` to persist or rely on the rollback on
    teardown. (Most repository tests commit, since the next assertion
    typically re-reads via the same session.)
    """
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide JWT_SECRET so tests that exercise jwt issuance don't fail
    with a config error. Tests that specifically test missing-env
    behaviour delete the var explicitly."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-do-not-use-in-production")
    monkeypatch.setenv("JWT_ISSUER", "maisys")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")
    monkeypatch.setenv("OTP_EXPIRE_MINUTES", "10")
    monkeypatch.setenv("OTP_MAX_ATTEMPTS", "3")
