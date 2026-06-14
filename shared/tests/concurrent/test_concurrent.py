"""Tests for shared.concurrent."""

from __future__ import annotations

import asyncio

import pytest

from shared.concurrent import BatchProcessor, gather_with_limit

# ─── gather_with_limit ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gather_with_limit_runs_all_coros() -> None:
    async def double(x: int) -> int:
        return x * 2

    results = await gather_with_limit(double(1), double(2), double(3), limit=2)
    assert results == [2, 4, 6]


@pytest.mark.asyncio
async def test_gather_with_limit_caps_concurrency() -> None:
    in_flight = 0
    peak = 0

    async def track() -> int:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return 1

    await gather_with_limit(*(track() for _ in range(8)), limit=3)
    assert peak <= 3


@pytest.mark.asyncio
async def test_gather_with_limit_return_exceptions_true() -> None:
    async def boom() -> int:
        raise RuntimeError("fail")

    async def ok() -> int:
        return 42

    results = await gather_with_limit(ok(), boom(), ok(), limit=2, return_exceptions=True)
    assert results[0] == 42
    assert isinstance(results[1], RuntimeError)
    assert results[2] == 42


@pytest.mark.asyncio
async def test_gather_with_limit_return_exceptions_false_raises() -> None:
    async def boom() -> int:
        raise RuntimeError("fail")

    async def ok() -> int:
        return 1

    with pytest.raises(RuntimeError):
        await gather_with_limit(ok(), boom(), limit=2)


def test_gather_with_limit_rejects_zero_limit() -> None:
    async def _r() -> None:
        with pytest.raises(ValueError):
            await gather_with_limit(limit=0)

    asyncio.run(_r())


# ─── BatchProcessor ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_processor_processes_all_items() -> None:
    async def square(x: int) -> int:
        return x * x

    proc = BatchProcessor[int, int](square, batch_size=3)
    results = await proc.run([1, 2, 3, 4, 5])
    assert results == [1, 4, 9, 16, 25]


@pytest.mark.asyncio
async def test_batch_processor_calls_progress_callback() -> None:
    async def identity(x: int) -> int:
        return x

    calls: list[tuple[int, int]] = []

    def on_progress(done: int, total: int) -> None:
        calls.append((done, total))

    proc = BatchProcessor[int, int](identity, batch_size=2, on_progress=on_progress)
    await proc.run([10, 20, 30, 40, 50])
    # 5 items → 5 progress callbacks. Last one is (5, 5).
    assert len(calls) == 5
    assert calls[-1] == (5, 5)


@pytest.mark.asyncio
async def test_batch_processor_async_progress_callback() -> None:
    async def identity(x: int) -> int:
        return x

    calls: list[tuple[int, int]] = []

    async def on_progress(done: int, total: int) -> None:
        calls.append((done, total))

    proc = BatchProcessor[int, int](identity, batch_size=2, on_progress=on_progress)
    await proc.run([1, 2, 3])
    assert calls[-1] == (3, 3)


@pytest.mark.asyncio
async def test_batch_processor_records_exceptions_in_results() -> None:
    async def maybe_fail(x: int) -> int:
        if x == 2:
            raise ValueError("two is bad")
        return x

    proc = BatchProcessor[int, int](maybe_fail, batch_size=3)
    results = await proc.run([1, 2, 3])
    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 3


def test_batch_processor_rejects_zero_batch_size() -> None:
    async def _x(x: int) -> int:
        return x

    with pytest.raises(ValueError):
        BatchProcessor[int, int](_x, batch_size=0)
