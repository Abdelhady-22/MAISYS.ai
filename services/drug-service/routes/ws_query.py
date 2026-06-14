"""WebSocket route for streaming drug-query progress.

Flow:

1. Client generates a ``job_id`` (UUID hex) and connects to
   ``/ws/drugs/query/{job_id}?token=<jwt>`` FIRST.
2. The WebSocket handler validates the JWT and subscribes to the
   ``progress:{job_id}`` Redis channel via ``ProgressSubscriber``.
3. Client then POSTs ``/drugs/query`` with the same ``job_id`` in
   the request body. The HTTP route passes it into the orchestrator
   context, so every ``ProgressEvent`` flows to ``progress:{job_id}``
   and is forwarded to this WebSocket.
4. When the orchestrator publishes ``status='completed'`` or
   ``status='failed'``, the WebSocket closes cleanly.

JWT auth uses a ``?token=`` query parameter (rather than the
``Authorization`` header used for HTTP) because browser WebSocket
APIs cannot set custom headers. The same JWT validation rules apply
— ``shared.auth.decode_token`` does the work.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from fastapi.websockets import WebSocketState

from shared.auth import decode_token
from shared.logger import get_logger
from shared.progress import ProgressEvent, ProgressSubscriber

_log = get_logger(__name__)

DEFAULT_IDLE_TIMEOUT_SECONDS = 60.0
"""Close the WebSocket if no progress event arrives for this long."""

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/drugs/query/{job_id}")
async def stream_query_progress(
    websocket: WebSocket,
    job_id: str,
    token: str = Query(
        ..., description="JWT bearer token (browsers can't set headers on WebSocket)"
    ),
) -> None:
    """Stream ``ProgressEvent`` messages for one job to a WebSocket client."""
    try:
        secret = os.environ.get("JWT_SECRET", "changeme_local_only")
        payload = decode_token(token, secret)
    except Exception as exc:
        _log.info("ws.auth.failed", job_id=job_id, error=str(exc))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    _log.info("ws.connected", job_id=job_id, user_id=payload.sub)

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    redis_client = aioredis.from_url(redis_url, decode_responses=False)

    try:
        idle_timeout = float(
            os.environ.get("WS_IDLE_TIMEOUT_SECONDS", DEFAULT_IDLE_TIMEOUT_SECONDS)
        )
        async with ProgressSubscriber(redis_client, job_id=job_id) as subscriber:
            await _pump_events(websocket, subscriber, idle_timeout, job_id)
    except WebSocketDisconnect:
        _log.info("ws.client_disconnected", job_id=job_id, user_id=payload.sub)
    except Exception as exc:
        _log.exception("ws.unexpected_error", job_id=job_id, error=str(exc))
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            except Exception:
                pass
    finally:
        await redis_client.aclose()


async def _pump_events(
    websocket: WebSocket,
    subscriber: ProgressSubscriber,
    idle_timeout: float,
    job_id: str,
) -> None:
    stream = subscriber.__aiter__()
    while True:
        try:
            event: ProgressEvent = await asyncio.wait_for(stream.__anext__(), timeout=idle_timeout)
        except asyncio.TimeoutError:
            _log.info("ws.idle_timeout", job_id=job_id, timeout_seconds=idle_timeout)
            await _send_safe(
                websocket,
                {
                    "status": "failed",
                    "message": f"Idle timeout — no progress for {idle_timeout}s",
                    "job_id": job_id,
                    "details": {"reason": "idle_timeout"},
                },
            )
            break
        except StopAsyncIteration:
            break

        await _send_safe(
            websocket,
            {
                "status": event.status,
                "message": event.message,
                "job_id": event.job_id,
                "percent": event.percent,
                "details": event.details,
            },
        )
        if event.status in {"completed", "failed"}:
            break

    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.close()


async def _send_safe(websocket: WebSocket, payload: dict[str, Any]) -> None:
    if websocket.client_state != WebSocketState.CONNECTED:
        return
    try:
        await websocket.send_json(payload)
    except Exception as exc:
        _log.info("ws.send_failed", error=str(exc))
