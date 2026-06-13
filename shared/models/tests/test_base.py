"""Tests for shared.models.base."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared.models.base import Base


# Define a probe model at module scope — SQLAlchemy needs to resolve
# the Mapped[] annotation in the enclosing module's globals, which doesn't
# work cleanly for classes defined inside a test function.
class _Probe(Base):
    __tablename__ = "_probe_base_test"

    id: Mapped[int] = mapped_column(primary_key=True)


def test_base_is_declarative_base_subclass() -> None:
    assert issubclass(Base, DeclarativeBase)


def test_base_has_metadata() -> None:
    assert hasattr(Base, "metadata")
    assert Base.metadata is not None


def test_base_is_subclassable() -> None:
    assert _Probe.__tablename__ == "_probe_base_test"
    assert "_probe_base_test" in Base.metadata.tables
