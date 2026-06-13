"""Tests for shared.models.mixins."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from shared.models.base import Base
from shared.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDMixin


# A model that exercises all three mixins — defined at module scope so it
# only registers with metadata once.
class _Widget(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "_widgets_mixin_test"

    name: Mapped[str] = mapped_column()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Fresh in-memory SQLite for each test, with StaticPool so the same
    connection is reused across queries (otherwise the in-memory DB vanishes
    between operations)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class TestUUIDMixin:
    @pytest.mark.asyncio
    async def test_id_is_uuid(self, session: AsyncSession) -> None:
        w = _Widget(name="probe")
        session.add(w)
        await session.commit()
        await session.refresh(w)
        assert isinstance(w.id, UUID)

    @pytest.mark.asyncio
    async def test_distinct_rows_have_distinct_ids(self, session: AsyncSession) -> None:
        a = _Widget(name="a")
        b = _Widget(name="b")
        session.add_all([a, b])
        await session.commit()
        await session.refresh(a)
        await session.refresh(b)
        assert a.id != b.id


class TestTimestampMixin:
    @pytest.mark.asyncio
    async def test_created_at_set_by_server(self, session: AsyncSession) -> None:
        w = _Widget(name="probe")
        session.add(w)
        await session.commit()
        await session.refresh(w)
        assert w.created_at is not None
        assert isinstance(w.created_at, datetime)

    @pytest.mark.asyncio
    async def test_updated_at_set_by_server(self, session: AsyncSession) -> None:
        w = _Widget(name="probe")
        session.add(w)
        await session.commit()
        await session.refresh(w)
        assert w.updated_at is not None
        assert isinstance(w.updated_at, datetime)


class TestSoftDeleteMixin:
    @pytest.mark.asyncio
    async def test_deleted_at_defaults_to_none(self, session: AsyncSession) -> None:
        w = _Widget(name="probe")
        session.add(w)
        await session.commit()
        await session.refresh(w)
        assert w.deleted_at is None

    @pytest.mark.asyncio
    async def test_can_mark_as_deleted(self, session: AsyncSession) -> None:
        w = _Widget(name="probe")
        session.add(w)
        await session.commit()

        # Mark deleted
        from datetime import timezone

        w.deleted_at = datetime.now(tz=timezone.utc)
        await session.commit()
        await session.refresh(w)
        assert w.deleted_at is not None


class TestMixinComposition:
    def test_widget_inherits_all_three(self) -> None:
        assert issubclass(_Widget, UUIDMixin)
        assert issubclass(_Widget, TimestampMixin)
        assert issubclass(_Widget, SoftDeleteMixin)
        assert issubclass(_Widget, Base)

    def test_all_mixin_columns_present(self) -> None:
        cols = {col.name for col in _Widget.__table__.columns}
        assert {"id", "created_at", "updated_at", "deleted_at", "name"} <= cols
