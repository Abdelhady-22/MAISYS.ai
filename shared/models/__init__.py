"""MAISYS shared models module — SQLAlchemy 2.0 async base for every service.

Provides:
- Base (DeclarativeBase) for all ORM models
- UUIDMixin, TimestampMixin, SoftDeleteMixin composable model mixins
- AsyncEngine + AsyncSession lifecycle: create_engine, create_session_factory,
  setup_db (module-level initialization), get_db_session (FastAPI dependency)
- PaginationParams + PaginatedResponse[T]
- Type aliases for cross-service consistency: ISOLanguageCode, ISOCountryCode,
  BilingualText, PercentFloat, PositiveFloat, Money

Typical service-side usage in main.py:

    from shared.models import setup_db
    setup_db(database_url=os.environ["DATABASE_URL"])

In a route:

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from shared.models import get_db_session

    @app.get("/users/{user_id}")
    async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db_session)):
        ...

In a model:

    from shared.models import Base, UUIDMixin, TimestampMixin, SoftDeleteMixin

    class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
        __tablename__ = "users"
        email: Mapped[str] = mapped_column(unique=True)
"""

from shared.models.base import Base
from shared.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDMixin
from shared.models.pagination import PaginatedResponse, PaginationParams
from shared.models.session import (
    create_engine,
    create_session_factory,
    get_db_session,
    get_session_factory,
    setup_db,
)
from shared.models.types import (
    BilingualText,
    ISOCountryCode,
    ISOLanguageCode,
    Money,
    PercentFloat,
    PositiveFloat,
)

__all__ = [
    "Base",
    "BilingualText",
    "ISOCountryCode",
    "ISOLanguageCode",
    "Money",
    "PaginatedResponse",
    "PaginationParams",
    "PercentFloat",
    "PositiveFloat",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDMixin",
    "create_engine",
    "create_session_factory",
    "get_db_session",
    "get_session_factory",
    "setup_db",
]
