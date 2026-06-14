"""Cross-service progress events via Redis pub/sub.

A ``ProgressPublisher`` emits events to a Redis channel
(``progress:{job_id}``); a ``ProgressSubscriber`` receives them. Used
by the ingesters and long-running drug-service agents to stream
progress to WebSocket clients.

The transport is Redis pub/sub via ``redis.asyncio``. Tests inject
``fakeredis.aioredis.FakeRedis`` so they don't need a real broker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

EventStatus = Literal["started", "in_progress", "completed", "failed"]


class ProgressEvent(BaseModel):
    """One progress update.

    ``percent`` is optional — many events don't have a meaningful
    progress fraction (e.g. ``status="completed"``). The model is
    JSON-serialisable for Redis transport.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    status: EventStatus
    message: str
    percent: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class RedisLike(Protocol):
    """Minimal subset of redis.asyncio.Redis we use, for test injection."""

    def publish(self, channel: str, message: str) -> Any: ...
    def pubsub(self) -> Any: ...


def _channel_for(job_id: str) -> str:
    return f"progress:{job_id}"


class ProgressPublisher:
    """Publishes ``ProgressEvent`` messages to the per-job Redis channel."""

    def __init__(self, redis_client: RedisLike) -> None:
        self._redis = redis_client

    async def publish(self, event: ProgressEvent) -> int:
        """Send ``event`` to channel ``progress:{job_id}``.

        Returns the number of subscribers Redis reports as having
        received the message. Zero is a normal outcome — events are
        fire-and-forget.
        """
        payload = event.model_dump_json()
        result = await self._redis.publish(_channel_for(event.job_id), payload)
        return int(result)


class ProgressSubscriber:
    """Subscribes to a per-job channel and yields ``ProgressEvent`` instances.

    Usage::

        async with ProgressSubscriber(redis, job_id="abc") as sub:
            async for event in sub:
                handle(event)
                if event.status in ("completed", "failed"):
                    break
    """

    def __init__(self, redis_client: RedisLike, *, job_id: str) -> None:
        self._redis = redis_client
        self._job_id = job_id
        self._pubsub: Any = None

    async def __aenter__(self) -> ProgressSubscriber:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(_channel_for(self._job_id))
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(_channel_for(self._job_id))
            await self._pubsub.close()
            self._pubsub = None

    async def __aiter__(self) -> AsyncIterator[ProgressEvent]:
        assert self._pubsub is not None, "use 'async with' before iterating"
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if data is None:
                continue
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            yield ProgressEvent.model_validate_json(data)


__all__ = [
    "EventStatus",
    "ProgressEvent",
    "ProgressPublisher",
    "ProgressSubscriber",
    "RedisLike",
]
