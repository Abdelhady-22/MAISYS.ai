"""Tests for shared.error_handler.handler with a real FastAPI app."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from shared.error_handler.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    MedicalSafetyException,
    NotFoundException,
    RateLimitException,
    ValidationException,
)
from shared.error_handler.handler import setup_exception_handlers


def _build_test_app() -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/not-found")
    async def _not_found() -> None:
        raise NotFoundException("Resource missing", details={"id": 1})

    @app.get("/validation")
    async def _validation() -> None:
        raise ValidationException(
            "Bad input", code="EMAIL_INVALID", details={"field": "email"}
        )

    @app.get("/auth-fail")
    async def _auth_fail() -> None:
        raise AuthenticationException("Token expired")

    @app.get("/forbidden")
    async def _forbidden() -> None:
        raise AuthorizationException("No access")

    @app.get("/conflict")
    async def _conflict() -> None:
        raise ConflictException("Duplicate email")

    @app.get("/rate-limit")
    async def _rate_limit() -> None:
        raise RateLimitException("Slow down")

    @app.get("/safety")
    async def _safety() -> None:
        raise MedicalSafetyException("Blocked")

    @app.get("/explode")
    async def _explode() -> None:
        raise RuntimeError("unexpected internal error with secret data: hunter2")

    @app.get("/correlation")
    async def _correlation(request: Request) -> None:
        request.state.request_id = "set-by-middleware"
        raise NotFoundException("missing")

    @app.get("/preset-correlation")
    async def _preset_correlation() -> None:
        # Exception already carries a correlation_id; handler must not overwrite it
        raise ValidationException("bad", correlation_id="preset-on-exc")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_test_app())


@pytest.fixture
def client_no_raise() -> TestClient:
    # raise_server_exceptions=False lets us assert on the 500 response body
    # rather than the test client re-raising the underlying exception
    return TestClient(_build_test_app(), raise_server_exceptions=False)


class TestMaisysExceptionHandler:
    @pytest.mark.parametrize(
        ("path", "expected_status", "expected_code"),
        [
            ("/not-found", 404, "NOT_FOUND"),
            ("/validation", 400, "EMAIL_INVALID"),
            ("/auth-fail", 401, "AUTHENTICATION_FAILED"),
            ("/forbidden", 403, "AUTHORIZATION_FAILED"),
            ("/conflict", 409, "CONFLICT"),
            ("/rate-limit", 429, "RATE_LIMITED"),
            ("/safety", 451, "MEDICAL_SAFETY_BLOCKED"),
        ],
    )
    def test_status_and_code_per_exception(
        self,
        client: TestClient,
        path: str,
        expected_status: int,
        expected_code: str,
    ) -> None:
        r = client.get(path)
        assert r.status_code == expected_status
        body = r.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == expected_code

    def test_envelope_shape(self, client: TestClient) -> None:
        r = client.get("/not-found")
        body = r.json()
        # Exhaustive envelope check
        assert set(body.keys()) == {"success", "data", "error", "metadata"}
        assert set(body["error"].keys()) == {
            "code",
            "message",
            "details",
            "correlation_id",
        }
        assert body["error"]["message"] == "Resource missing"
        assert body["error"]["details"] == {"id": 1}

    def test_correlation_id_pulled_from_request_state(
        self, client: TestClient
    ) -> None:
        r = client.get("/correlation")
        body = r.json()
        assert body["error"]["correlation_id"] == "set-by-middleware"

    def test_correlation_id_preset_on_exception_preserved(
        self, client: TestClient
    ) -> None:
        # When the exception was raised with its own correlation_id, the handler
        # must NOT overwrite it with request.state (which is unset here).
        r = client.get("/preset-correlation")
        body = r.json()
        assert body["error"]["correlation_id"] == "preset-on-exc"


class TestUnhandledExceptionHandler:
    def test_returns_generic_500(self, client_no_raise: TestClient) -> None:
        r = client_no_raise.get("/explode")
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message"] == "An internal error occurred"

    def test_does_not_leak_exception_detail(
        self, client_no_raise: TestClient
    ) -> None:
        r = client_no_raise.get("/explode")
        # Critically: the secret in the underlying exception MUST NOT leak
        assert "hunter2" not in r.text
        assert "RuntimeError" not in r.text
        assert "unexpected internal" not in r.text
