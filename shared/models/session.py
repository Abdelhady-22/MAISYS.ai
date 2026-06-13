"""Async engine and session lifecycle for MAISYS services.

Each service calls `setup_db(database_url)` once at startup (typically from
main.py), then uses `get_db_session` as a FastAPI dependency in routes.

The module-level factory variable is intentionally simple — one factory per
process, set once. Services that need multiple databases (rare) can manage
their own factories using `create_engine` + `create_session_factory` directly.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Module-level state, initialized by setup_db().
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Create an AsyncEngine with sensible defaults for service usage.

    Defaults:
    - pool_size=10, max_overflow=20: handles a typical service workload
      (skipped if the caller overrides `poolclass`, since not all pool
      classes accept these — notably StaticPool used in tests)
    - pool_pre_ping=True: detects stale connections after Postgres restarts
    - pool_recycle=1800: rotates connections every 30 minutes
    - echo=False: never log SQL by default

    Any caller-supplied kwargs override the defaults.
    """
    defaults: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "echo": False,
    }
    # pool_size and max_overflow only apply to QueuePool (the default). If
    # the caller is using a different pool class (e.g. StaticPool for
    # in-memory SQLite tests), these kwargs would raise TypeError.
    if "poolclass" not in kwargs:
        defaults["pool_size"] = 10
        defaults["max_overflow"] = 20
    defaults.update(kwargs)
    return create_async_engine(database_url, **defaults)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Build an async_sessionmaker with MAISYS defaults.

    expire_on_commit=False: after a commit, attributes on returned ORM
    instances remain accessible without re-fetching. This is the correct
    setting for async services where the caller often needs to serialize
    a model after committing.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def setup_db(database_url: str, **engine_kwargs: Any) -> None:
    """Initialize the module-level session factory.

    Call once at service startup, before any request that needs a session.
    Subsequent calls replace the factory (useful in tests).
    """
    global _session_factory
    engine = create_engine(database_url, **engine_kwargs)
    _session_factory = create_session_factory(engine)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the configured session factory.

    Raises RuntimeError if setup_db() has not been called. This is a
    deliberate hard failure — silently creating an in-memory or default
    engine would mask configuration bugs.
    """
    if _session_factory is None:
        raise RuntimeError(
            "setup_db(database_url=...) must be called before requesting "
            "a session. Typical place: your service's main.py at startup."
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield an AsyncSession.

    Lifecycle:
    - Open a new session from the configured factory
    - Yield it to the route handler
    - On normal return: commit the session
    - On exception: roll back, then re-raise
    - Always: close the session (handled by `async with` on the factory)

    Note that if the route handler explicitly commits, the auto-commit at
    the end becomes a no-op (SQLAlchemy is idempotent on commit of a
    flushed/committed session). Mixing explicit and implicit commits is
    safe but typically not necessary.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
