"""Tests for the per-model circuit breaker."""

from __future__ import annotations

import asyncio

import pytest

from shared.error_handler import ExternalServiceException
from shared.llm_client import CircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_closed_breaker_runs_call() -> None:
    breaker = CircuitBreaker()
    result = await breaker.call("model-a", _make_call(returns=42))
    assert result == 42
    assert breaker.state_of("model-a") is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_consecutive_failures_open_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await breaker.call("model-b", _make_call(raises=RuntimeError("boom")))
    assert breaker.state_of("model-b") is CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_breaker_rejects_until_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.05)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call("m", _make_call(raises=RuntimeError("x")))
    # Immediately: rejected
    with pytest.raises(ExternalServiceException):
        await breaker.call("m", _make_call(returns=1))
    # After cooldown: half-open, first call goes through
    await asyncio.sleep(0.07)
    result = await breaker.call("m", _make_call(returns=99))
    assert result == 99
    assert breaker.state_of("m") is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_reopens_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    with pytest.raises(RuntimeError):
        await breaker.call("m", _make_call(raises=RuntimeError("a")))
    assert breaker.state_of("m") is CircuitState.OPEN
    await asyncio.sleep(0.07)
    # Half-open probe also fails: re-opens
    with pytest.raises(RuntimeError):
        await breaker.call("m", _make_call(raises=RuntimeError("b")))
    assert breaker.state_of("m") is CircuitState.OPEN


@pytest.mark.asyncio
async def test_success_resets_failure_counter() -> None:
    breaker = CircuitBreaker(failure_threshold=3)
    with pytest.raises(RuntimeError):
        await breaker.call("m", _make_call(raises=RuntimeError("fail")))
    await breaker.call("m", _make_call(returns=1))
    # Now we should need a fresh 3 failures to open
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call("m", _make_call(raises=RuntimeError("fail")))
    assert breaker.state_of("m") is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_different_models_have_independent_circuits() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call("model-x", _make_call(raises=RuntimeError("boom")))
    # model-x is OPEN; model-y still CLOSED
    assert breaker.state_of("model-x") is CircuitState.OPEN
    assert breaker.state_of("model-y") is CircuitState.CLOSED
    result = await breaker.call("model-y", _make_call(returns=7))
    assert result == 7


def _make_call(*, returns: object = None, raises: BaseException | None = None):
    async def _call() -> object:
        if raises is not None:
            raise raises
        return returns

    return _call
