"""Tests for shared.progress (via fakeredis)."""

from __future__ import annotations

import asyncio

import pytest

fakeredis = pytest.importorskip("fakeredis")

from shared.progress import (  # noqa: E402
    ProgressEvent,
    ProgressPublisher,
    ProgressSubscriber,
)


def _make_redis() -> object:
    return fakeredis.aioredis.FakeRedis()


def test_progress_event_serialises_to_json() -> None:
    event = ProgressEvent(job_id="abc", status="started", message="Begin")
    payload = event.model_dump_json()
    restored = ProgressEvent.model_validate_json(payload)
    assert restored.job_id == "abc"
    assert restored.status == "started"
    assert restored.message == "Begin"


def test_progress_event_optional_percent_defaults_to_none() -> None:
    event = ProgressEvent(job_id="x", status="completed", message="done")
    assert event.percent is None


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_returns_zero() -> None:
    redis = _make_redis()
    pub = ProgressPublisher(redis)
    n = await pub.publish(ProgressEvent(job_id="lonely", status="started", message="hello"))
    assert n == 0


@pytest.mark.asyncio
async def test_publish_and_subscribe_roundtrip() -> None:
    redis = _make_redis()
    pub = ProgressPublisher(redis)
    events_received: list[ProgressEvent] = []

    async def consume() -> None:
        async with ProgressSubscriber(redis, job_id="job-1") as sub:
            async for event in sub:
                events_received.append(event)
                if event.status == "completed":
                    return

    consumer = asyncio.create_task(consume())
    # Give the subscriber time to register
    await asyncio.sleep(0.05)

    await pub.publish(ProgressEvent(job_id="job-1", status="started", message="Begin"))
    await pub.publish(
        ProgressEvent(job_id="job-1", status="in_progress", message="50%", percent=50.0)
    )
    await pub.publish(ProgressEvent(job_id="job-1", status="completed", message="done"))

    await asyncio.wait_for(consumer, timeout=2)
    assert len(events_received) == 3
    assert events_received[0].status == "started"
    assert events_received[1].percent == 50.0
    assert events_received[2].status == "completed"


@pytest.mark.asyncio
async def test_subscriber_only_receives_its_job_channel() -> None:
    redis = _make_redis()
    pub = ProgressPublisher(redis)
    received: list[ProgressEvent] = []

    async def consume() -> None:
        async with ProgressSubscriber(redis, job_id="job-A") as sub:
            async for event in sub:
                received.append(event)
                if event.status == "completed":
                    return

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)

    # Other job's events should NOT be received
    await pub.publish(ProgressEvent(job_id="job-B", status="started", message="other"))
    await pub.publish(ProgressEvent(job_id="job-A", status="completed", message="mine"))

    await asyncio.wait_for(consumer, timeout=2)
    assert len(received) == 1
    assert received[0].job_id == "job-A"
