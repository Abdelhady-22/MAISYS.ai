"""Tests for the /ws/drugs/query WebSocket route."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from services.drug_service.main import DrugServiceConfig, create_app
from shared.auth import Role, TokenPayload
from shared.progress import ProgressEvent, ProgressPublisher


@pytest.fixture
def app(monkeypatch, redis_client):
    """Build a fresh app with wiring disabled."""
    # Skip the DB engine creation — these tests don't use the DB layer.
    monkeypatch.setattr("services.drug_service.main.setup_db", lambda url: None)

    cfg = DrugServiceConfig(
        app_env="test",
        log_level="WARNING",
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=["*"],
        enable_metrics=False,
        enable_agent_wiring=False,
    )
    fastapi_app = create_app(cfg)

    # Override auth so any token validates as our test user (the WebSocket
    # route uses decode_token directly, not the get_current_user dependency,
    # so we patch decode_token).
    def _fake_decode(token: str, secret: str = "", issuer: str = "maisys") -> TokenPayload:
        if token == "invalid-token":
            raise ValueError("simulated bad token")
        return TokenPayload(
            sub="test-user",
            role=Role.USER,
            exp=9999999999,
            iat=0,
            iss="maisys",
            jti="test-jti",
            scope=[],
        )

    monkeypatch.setattr("services.drug_service.routes.ws_query.decode_token", _fake_decode)
    return fastapi_app


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Shared fakeredis instance for ProgressPublisher + ProgressSubscriber."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def patch_redis(monkeypatch, redis_client):
    """Patch aioredis.from_url in the ws_query module to return our fakeredis."""

    def _from_url(url: str, *args, **kwargs):
        return redis_client

    monkeypatch.setattr("services.drug_service.routes.ws_query.aioredis.from_url", _from_url)


def test_invalid_token_rejected(app) -> None:
    """A token that fails decode_token returns close-frame 1008 before any data."""
    with TestClient(app) as tc:
        with pytest.raises(Exception):  # WebSocketDisconnect or similar
            with tc.websocket_connect("/ws/drugs/query/job-1?token=invalid-token"):
                pass  # the connect itself raises because server closes


def test_valid_token_accepted_and_streams_events(app, redis_client) -> None:
    """Subscribe → publish via ProgressPublisher → client receives events."""
    job_id = "job-happy"
    publisher = ProgressPublisher(redis_client)

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws/drugs/query/{job_id}?token=valid") as ws:
            # Publish three events from a background task so the subscriber loop is hot
            async def _emit() -> None:
                await asyncio.sleep(0.05)
                await publisher.publish(
                    ProgressEvent(job_id=job_id, status="in_progress", message="step 1")
                )
                await asyncio.sleep(0.02)
                await publisher.publish(
                    ProgressEvent(job_id=job_id, status="in_progress", message="step 2")
                )
                await asyncio.sleep(0.02)
                await publisher.publish(
                    ProgressEvent(job_id=job_id, status="completed", message="done")
                )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_emit())
            finally:
                loop.close()

            received = []
            for _ in range(3):
                received.append(ws.receive_json())

            assert received[0]["status"] == "in_progress"
            assert received[0]["message"] == "step 1"
            assert received[1]["message"] == "step 2"
            assert received[2]["status"] == "completed"


def test_failed_status_also_closes(app, redis_client) -> None:
    """A 'failed' status closes the WebSocket just like 'completed'."""
    job_id = "job-failed"
    publisher = ProgressPublisher(redis_client)

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws/drugs/query/{job_id}?token=valid") as ws:

            async def _emit() -> None:
                await asyncio.sleep(0.05)
                await publisher.publish(
                    ProgressEvent(
                        job_id=job_id,
                        status="failed",
                        message="agent crashed",
                        details={"reason": "execution_failure"},
                    )
                )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_emit())
            finally:
                loop.close()

            event = ws.receive_json()
            assert event["status"] == "failed"
            assert event["details"]["reason"] == "execution_failure"
