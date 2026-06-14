"""Route-test fixtures.

The `app_for(router)` factory builds a FastAPI app with the given
router(s) mounted, exception handlers wired, and the database
dependency overridden to use the test ``db_session``.

The `make_client(*routers)` fixture is an async context manager that
yields an httpx.AsyncClient bound to the app::

    async with make_client(register_router) as client:
        response = await client.post(...)

The `auth_headers(user)` helper mints a fresh access token for the
given User and returns the Authorization header dict, so tests of
protected endpoints can write::

    response = await client.get("/auth/me", headers=auth_headers(user))
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User
from repository import UserRepository
from shared.auth import Role
from shared.error_handler import setup_exception_handlers
from shared.models import get_db_session
from utils.jwt import issue_access_token
from utils.password import hash_password


@pytest.fixture
def app_for(db_session: AsyncSession) -> Callable[..., FastAPI]:
    """Return a factory that builds a FastAPI app from one or more routers.

    The factory accepts a variable number of APIRouter instances and
    mounts them all onto a fresh app, with exception handlers wired and
    ``get_db_session`` overridden to yield the test session.
    """

    def _build(*routers: APIRouter) -> FastAPI:
        app = FastAPI()
        setup_exception_handlers(app)

        async def _override_get_db() -> AsyncIterator[AsyncSession]:
            yield db_session

        app.dependency_overrides[get_db_session] = _override_get_db
        for r in routers:
            app.include_router(r)
        return app

    return _build


@pytest.fixture
def make_client(
    app_for: Callable[..., FastAPI],
) -> Callable[..., _AsyncGeneratorContextManager[AsyncClient]]:
    """Return a factory: ``async with make_client(router) as client``."""

    @asynccontextmanager
    async def _factory(*routers: APIRouter) -> AsyncIterator[AsyncClient]:
        app = app_for(*routers)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    return _factory


def auth_headers(user: User, scope: list[str] | None = None) -> dict[str, str]:
    """Mint a Bearer token header for the given user."""
    token, _ = issue_access_token(str(user.id), Role(user.role), scope=scope)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def verified_user(db_session: AsyncSession) -> User:
    """A user fixture with email_verified=True and a known password.

    Most route tests need this — `email_verified=False` would short-
    circuit login. The password is "TestP@ssw0rd1" so tests can submit
    the same value to /auth/login.
    """
    repo = UserRepository(db_session)
    user = await repo.create(
        email="verified@example.com",
        password_hash=hash_password("TestP@ssw0rd1"),
    )
    await repo.mark_email_verified(user.id)
    await db_session.commit()
    await db_session.refresh(user)
    return user
