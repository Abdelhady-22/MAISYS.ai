"""Tests for shared.auth.rbac.require_role."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from shared.auth.rbac import require_role
from shared.auth.types import Role, TokenPayload
from shared.error_handler import setup_exception_handlers

_TEST_SECRET = "test-secret-do-not-use-in-production-7e3a9c1f"
_TEST_ISSUER = "maisys"


@pytest.fixture(autouse=True)
def _set_jwt_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
    monkeypatch.setenv("JWT_ISSUER", _TEST_ISSUER)
    yield


def _make_token(role: str) -> str:
    now = int(time.time())
    return cast(
        str,
        jwt.encode(
            {
                "sub": "user-1",
                "role": role,
                "exp": now + 3600,
                "iat": now,
                "iss": _TEST_ISSUER,
                "jti": "j-test",
            },
            _TEST_SECRET,
            algorithm="HS256",
        ),
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get(
        "/admin-only",
        dependencies=[Depends(require_role(Role.ADMIN))],
    )
    async def admin_only() -> dict[str, str]:
        return {"ok": "admin"}

    @app.get("/admin-and-super")
    async def admin_and_super(
        user: TokenPayload = Depends(require_role(Role.ADMIN, Role.SUPER_ADMIN)),
    ) -> dict[str, str]:
        return {"user_id": user.sub, "role": user.role.value}

    @app.get(
        "/premium-or-higher",
        dependencies=[Depends(require_role(Role.PREMIUM, Role.ADMIN, Role.SUPER_ADMIN))],
    )
    async def premium_or_higher() -> dict[str, str]:
        return {"ok": "premium"}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestRoleAllowed:
    def test_admin_can_access_admin_route(self, client: TestClient) -> None:
        r = client.get("/admin-only", headers=_auth(_make_token("admin")))
        assert r.status_code == 200

    def test_admin_can_access_admin_or_super(self, client: TestClient) -> None:
        r = client.get("/admin-and-super", headers=_auth(_make_token("admin")))
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_super_admin_can_access_admin_or_super(self, client: TestClient) -> None:
        r = client.get("/admin-and-super", headers=_auth(_make_token("super_admin")))
        assert r.status_code == 200
        assert r.json()["role"] == "super_admin"

    def test_premium_can_access_premium_or_higher(self, client: TestClient) -> None:
        r = client.get("/premium-or-higher", headers=_auth(_make_token("premium")))
        assert r.status_code == 200


class TestRoleDenied:
    def test_user_cannot_access_admin(self, client: TestClient) -> None:
        r = client.get("/admin-only", headers=_auth(_make_token("user")))
        assert r.status_code == 403
        body = r.json()
        assert body["success"] is False
        assert body["error"]["code"] == "ROLE_NOT_ALLOWED"
        # Details should expose what was required vs actual
        details = body["error"]["details"]
        assert details["actual"] == "user"
        assert details["required"] == ["admin"]

    def test_user_cannot_access_admin_and_super(self, client: TestClient) -> None:
        r = client.get("/admin-and-super", headers=_auth(_make_token("user")))
        assert r.status_code == 403
        details = r.json()["error"]["details"]
        assert details["required"] == ["admin", "super_admin"]

    def test_premium_cannot_access_admin(self, client: TestClient) -> None:
        r = client.get("/admin-only", headers=_auth(_make_token("premium")))
        assert r.status_code == 403

    def test_user_cannot_access_premium_or_higher(self, client: TestClient) -> None:
        r = client.get("/premium-or-higher", headers=_auth(_make_token("user")))
        assert r.status_code == 403


class TestRoleAuthFlow:
    def test_no_token_returns_401_not_403(self, client: TestClient) -> None:
        # Authentication failure should win over authorization failure
        r = client.get("/admin-only")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "AUTH_HEADER_MISSING"

    def test_invalid_token_returns_401_not_403(self, client: TestClient) -> None:
        r = client.get("/admin-only", headers={"Authorization": "Bearer bad.token"})
        assert r.status_code == 401


class TestRequireRoleConstruction:
    def test_no_roles_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one Role"):
            require_role()
