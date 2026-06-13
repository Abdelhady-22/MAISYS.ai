"""Composable ORM mixins for MAISYS models.

UUIDMixin     — provides a uuid4 primary key column `id`
TimestampMixin — provides `created_at` and `updated_at` with server-side defaults
SoftDeleteMixin — provides a nullable `deleted_at` column for soft deletes

Mixins compose via multiple inheritance:

    class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
        __tablename__ = "users"
        email: Mapped[str] = mapped_column(unique=True)

`MappedAsDataclass` is intentionally not used — services that want dataclass
behavior can opt in per-model.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDMixin:
    """Adds a uuid4 primary key column named `id`."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class TimestampMixin:
    """Adds `created_at` and `updated_at` columns.

    Both default to the database's current timestamp (server_default=func.now()).
    `updated_at` is also updated on every UPDATE via onupdate=func.now().

    Note on cross-database behavior:
    - PostgreSQL honors onupdate=func.now() at the SQL level (requires the
      UPDATE statement to be issued via SQLAlchemy).
    - SQLite honors it the same way through SQLAlchemy's ORM layer; raw SQL
      bypasses it.
    Either way, services should always go through the ORM, so this works.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds a nullable `deleted_at` column for soft-delete semantics.

    A row is considered "deleted" when `deleted_at IS NOT NULL`. Repositories
    are responsible for filtering soft-deleted rows out of normal queries
    (typically via a default `deleted_at.is_(None)` clause).
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )
