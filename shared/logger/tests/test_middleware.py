"""Tests for shared.logger.middleware.RequestLoggingMiddleware."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Iterator

import pytest
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from shared.logger.config import configure_logging
from shared.logger.middleware import RequestLoggingMiddleware

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture(autouse=True)
def _reset_structlog_between_tests() -> Iterator[None]:
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(logging.WARNING)
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def _build_app() -> FastAPI:
    configure_logging(env="ci", log_level="INFO")
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, service_name="test-service")

    @app.get("/")
    async def _root() -> dict[str, str]:
        return {"hello": "world"}

    @app.get("/peek-context")
    async def _peek_context() -> dict[str, object]:
        return dict(structlog.contextvars.get_contextvars())

    @app.get("/peek-request-state")
    async def _peek_state(request: Request) -> dict[str, str]:
        return {"request_id": getattr(request.state, "request_id", "<unset>")}

    @app.get("/explode")
    async def _explode() -> None:
        raise RuntimeError("boom")

    @app.get("/http-error")
    async def _http_error() -> None:
        raise HTTPException(status_code=400, detail="bad")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


@pytest.fixture
def client_no_raise() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


def _middleware_events(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Collect 'event' fields from middleware log records captured by caplog.

    structlog with stdlib integration emits records whose .msg is the structlog
    event dict; we read the 'event' key directly.
    """
    events: list[str] = []
    for record in caplog.records:
        if record.name != "shared.logger.middleware":
            continue
        if isinstance(record.msg, dict):
            event = record.msg.get("event")
            if isinstance(event, str):
                events.append(event)
        else:
            events.append(str(record.msg))
    return events


def _completed_record_msg(
    caplog: pytest.LogCaptureFixture,
) -> dict[str, object]:
    """Return the event dict of the request.completed log record (or fail)."""
    for record in caplog.records:
        if record.name != "shared.logger.middleware":
            continue
        if isinstance(record.msg, dict) and record.msg.get("event") == "request.completed":
            return record.msg
    pytest.fail("Expected a request.completed log record")


class TestRequestId:
    def test_generated_when_no_header(self, client: TestClient) -> None:
        r = client.get("/")
        assert "X-Request-ID" in r.headers
        rid = r.headers["X-Request-ID"]
        assert _UUID_RE.match(rid), f"Not a UUID: {rid}"
        uuid.UUID(rid)

    def test_honored_from_header(self, client: TestClient) -> None:
        r = client.get("/", headers={"X-Request-ID": "my-trace-id-123"})
        assert r.headers["X-Request-ID"] == "my-trace-id-123"

    def test_set_on_request_state(self, client: TestClient) -> None:
        r = client.get("/peek-request-state", headers={"X-Request-ID": "trace-abc"})
        assert r.json() == {"request_id": "trace-abc"}

    def test_set_on_request_state_when_no_header(self, client: TestClient) -> None:
        r = client.get("/peek-request-state")
        body = r.json()
        assert _UUID_RE.match(body["request_id"])


class TestContextvarsBinding:
    def test_bound_during_request(self, client: TestClient) -> None:
        r = client.get("/peek-context", headers={"X-Request-ID": "trace-123"})
        ctx = r.json()
        assert ctx["request_id"] == "trace-123"
        assert ctx["method"] == "GET"
        assert ctx["path"] == "/peek-context"
        assert ctx["service"] == "test-service"

    def test_method_and_path_reflect_actual_request(self, client: TestClient) -> None:
        r = client.get("/peek-context")
        ctx = r.json()
        assert ctx["method"] == "GET"
        assert ctx["path"] == "/peek-context"


class TestLogEvents:
    def test_request_started_and_completed_logged(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="shared.logger.middleware"):
            client.get("/", headers={"X-Request-ID": "trace-1"})
        events = _middleware_events(caplog)
        assert "request.started" in events
        assert "request.completed" in events

    def test_completed_log_has_status_and_duration(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="shared.logger.middleware"):
            client.get("/")
        msg = _completed_record_msg(caplog)
        assert msg["status_code"] == 200
        assert "duration_ms" in msg
        assert isinstance(msg["duration_ms"], int)

    def test_request_failed_logged_on_exception(
        self,
        client_no_raise: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="shared.logger.middleware"):
            client_no_raise.get("/explode")
        events = _middleware_events(caplog)
        assert "request.started" in events
        assert "request.failed" in events
        # request.completed should NOT be logged on failure
        assert "request.completed" not in events

    def test_http_exception_completes_normally(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        # FastAPI's HTTPException is converted to a 4xx response by FastAPI's
        # built-in handler — it does NOT propagate as a Python exception to our
        # middleware, so we should see request.completed (not request.failed).
        with caplog.at_level(logging.INFO, logger="shared.logger.middleware"):
            client.get("/http-error")
        events = _middleware_events(caplog)
        assert "request.completed" in events
        assert "request.failed" not in events
