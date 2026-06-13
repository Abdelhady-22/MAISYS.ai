"""Tests for shared.auth.dependencies."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from shared.auth.dependencies import get_current_user, get_current_user_optional
from shared.auth.types import TokenPayload
from shared.error_handler import setup_exception_handlers

_TEST_SECRET = "test-secret-do-not-use-in-production-7e3a9c1f"
_TEST_ISSUER = "maisys"


@pytest.fixture(autouse=True)
def _set_jwt_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
    monkeypatch.setenv("JWT_ISSUER", _TEST_ISSUER)
    yield


def _make_token(role: str = "user", sub: str = "user-1") -> str:
    now = int(time.time())
    return cast(
        str,
        jwt.encode(
            {
                "sub": sub,
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

    @app.get("/protected")
    async def protected(user: TokenPayload = Depends(get_current_user)) -> dict[str, str]:
        return {"user_id": user.sub, "role": user.role.value}

    @app.get("/maybe")
    async def maybe(
        user: TokenPayload | None = Depends(get_current_user_optional),
    ) -> dict[str, str | None]:
        return {"user_id": user.sub if user else None}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


class TestGetCurrentUser:
    def test_valid_token(self, client: TestClient) -> None:
        token = _make_token(role="admin", sub="user-42")
        r = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "user-42"
        assert body["role"] == "admin"

    def test_no_header(self, client: TestClient) -> None:
        r = client.get("/protected")
        assert r.status_code == 401
        body = r.json()
        assert body["success"] is False
        assert body["error"]["code"] == "AUTH_HEADER_MISSING"

    def test_no_bearer_prefix(self, client: TestClient) -> None:
        token = _make_token()
        r = client.get("/protected", headers={"Authorization": token})
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "AUTH_HEADER_INVALID"

    def test_bearer_with_empty_token(self, client: TestClient) -> None:
        r = client.get("/protected", headers={"Authorization": "Bearer "})
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "AUTH_HEADER_INVALID"

    def test_wrong_scheme(self, client: TestClient) -> None:
        token = _make_token()
        r = client.get("/protected", headers={"Authorization": f"Basic {token}"})
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "AUTH_HEADER_INVALID"

    def test_invalid_token(self, client: TestClient) -> None:
        r = client.get("/protected", headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "TOKEN_INVALID_SIGNATURE"


class TestGetCurrentUserOptional:
    def test_no_header_returns_none(self, client: TestClient) -> None:
        r = client.get("/maybe")
        assert r.status_code == 200
        assert r.json() == {"user_id": None}

    def test_valid_token_returns_user(self, client: TestClient) -> None:
        token = _make_token(sub="user-7")
        r = client.get("/maybe", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"user_id": "user-7"}

    def test_invalid_token_raises_does_not_silently_anonymize(self, client: TestClient) -> None:
        # Critical security property: a present-but-bad token must NOT be
        # treated as "anonymous" — that would let expired tokens through
        # on routes that gracefully degrade.
        r = client.get("/maybe", headers={"Authorization": "Bearer garbage.token.value"})
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "TOKEN_INVALID_SIGNATURE"


class TestMissingJWTSecret:
    def test_raises_runtime_error_when_secret_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Remove JWT_SECRET, leaving JWT_ISSUER intact
        monkeypatch.delenv("JWT_SECRET", raising=False)
        client = TestClient(_build_app(), raise_server_exceptions=False)
        token = _make_token()
        r = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        # Missing secret is a configuration error → returns generic 500
        # without leaking the reason
        assert r.status_code == 500
        body = r.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "JWT_SECRET" not in r.text
