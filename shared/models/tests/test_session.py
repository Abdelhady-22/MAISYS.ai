"""Tests for shared.models.session."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from shared.models import session as session_module
from shared.models.session import (
    create_engine,
    create_session_factory,
    get_db_session,
    get_session_factory,
    setup_db,
)


@pytest.fixture(autouse=True)
def _reset_session_module_state() -> Iterator[None]:
    """Each test starts with the module's _session_factory cleared so we
    can deterministically test setup/teardown behavior."""
    session_module._session_factory = None
    yield
    session_module._session_factory = None


def _sqlite_kwargs() -> dict[str, object]:
    """SQLAlchemy kwargs for an in-memory SQLite that survives across calls."""
    return {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestCreateEngine:
    def test_returns_engine(self) -> None:
        eng = create_engine("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        assert eng is not None

    def test_caller_kwargs_override_defaults(self) -> None:
        # echo=False is the default; setting echo=True should be honored
        eng = create_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=True,
            **_sqlite_kwargs(),
        )
        assert eng.echo is True


class TestCreateSessionFactory:
    def test_returns_factory(self) -> None:
        eng = create_engine("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        factory = create_session_factory(eng)
        assert factory is not None


class TestSetupDb:
    def test_sets_module_factory(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        assert session_module._session_factory is not None

    def test_replaces_previous_factory(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        first = session_module._session_factory
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        second = session_module._session_factory
        assert first is not second


class TestGetSessionFactory:
    def test_returns_factory_after_setup(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        factory = get_session_factory()
        assert factory is not None

    def test_raises_when_not_setup(self) -> None:
        # Fixture cleared the factory before this test
        with pytest.raises(RuntimeError, match="setup_db"):
            get_session_factory()


class TestGetDbSession:
    @pytest.mark.asyncio
    async def test_yields_a_session(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        async for session in get_db_session():
            assert isinstance(session, AsyncSession)
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_yields_exactly_once(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        count = 0
        async for _ in get_db_session():
            count += 1
        assert count == 1

    @pytest.mark.asyncio
    async def test_commit_on_success(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        # Run a write, then on a fresh session verify it persisted.
        # Using a temp table because we're not loading any models here.
        async for s in get_db_session():
            await s.execute(text("CREATE TABLE t (v INTEGER)"))
            await s.execute(text("INSERT INTO t (v) VALUES (42)"))

        async for s in get_db_session():
            result = await s.execute(text("SELECT v FROM t"))
            assert result.scalar() == 42

    @pytest.mark.asyncio
    async def test_rollback_on_exception(self) -> None:
        setup_db("sqlite+aiosqlite:///:memory:", **_sqlite_kwargs())
        # Create the table in a successful first transaction
        async for s in get_db_session():
            await s.execute(text("CREATE TABLE t2 (v INTEGER)"))

        # Now insert and then raise — the row must NOT persist
        with pytest.raises(ValueError, match="simulated"):
            async for s in get_db_session():
                await s.execute(text("INSERT INTO t2 (v) VALUES (99)"))
                raise ValueError("simulated failure")

        async for s in get_db_session():
            result = await s.execute(text("SELECT COUNT(*) FROM t2"))
            assert result.scalar() == 0

    @pytest.mark.asyncio
    async def test_raises_if_not_setup(self) -> None:
        # Fixture cleared the factory; get_db_session must raise on first use
        with pytest.raises(RuntimeError, match="setup_db"):
            async for _ in get_db_session():
                pass
