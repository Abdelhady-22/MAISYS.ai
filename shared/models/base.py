"""SQLAlchemy declarative base for all MAISYS ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common SQLAlchemy 2.0 DeclarativeBase for every MAISYS service.

    Every concrete model in any service should subclass this (plus any
    desired mixins). Sharing one Base means metadata is global, which
    matters for tooling that introspects all models (Alembic, schema diff,
    etc.). In practice, each service runs its own Alembic environment
    against its own database, so cross-service tables never share state.
    """
