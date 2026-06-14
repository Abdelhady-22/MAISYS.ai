"""Per-model circuit breaker for the LLM client.

States:

* ``CLOSED`` — normal operation. Failures increment a counter; on the
  ``threshold``-th consecutive failure, the breaker trips to ``OPEN``.
* ``OPEN`` — calls fail fast with ``ExternalServiceException`` until
  ``cooldown_seconds`` have passed. The next attempt transitions to
  ``HALF_OPEN``.
* ``HALF_OPEN`` — exactly one probe call is allowed through. On
  success, the breaker closes and the failure counter resets. On
  failure, the breaker re-opens and the cooldown restarts.

The breaker is keyed by ``(provider, model)``. Different routes to
the same model on different providers (``openai/gpt-4o`` vs
``azure/gpt-4o``) get independent circuits.

Failures specifically tracked are: any exception raised by the
backend. The caller decides what to wrap in ``with_circuit()`` —
parse errors and validation failures should NOT be tracked.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from shared.error_handler import ExternalServiceException
from shared.logger import get_logger

_log = get_logger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _CircuitData:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CircuitBreaker:
    """Async, in-memory, per-key circuit breaker.

    For multi-process deployments the same breaker state can be backed
    by Redis later; the public API will not change.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._circuits: dict[str, _CircuitData] = {}
        self._global_lock = asyncio.Lock()

    async def _circuit(self, key: str) -> _CircuitData:
        async with self._global_lock:
            circuit = self._circuits.get(key)
            if circuit is None:
                circuit = _CircuitData()
                self._circuits[key] = circuit
            return circuit

    async def call(self, key: str, func: Callable[[], Awaitable[T]]) -> T:
        """Invoke ``func`` through the breaker keyed by ``key``."""
        circuit = await self._circuit(key)
        async with circuit.lock:
            now = time.monotonic()
            if circuit.state is CircuitState.OPEN:
                if now - circuit.opened_at < self._cooldown_seconds:
                    _log.warning("llm.circuit.rejected", key=key, state=circuit.state.value)
                    raise ExternalServiceException(
                        f"Circuit breaker open for {key}; not attempting call"
                    )
                circuit.state = CircuitState.HALF_OPEN
                _log.info("llm.circuit.half_open", key=key)

        try:
            result = await func()
        except Exception:
            async with circuit.lock:
                if circuit.state is CircuitState.HALF_OPEN:
                    circuit.state = CircuitState.OPEN
                    circuit.opened_at = time.monotonic()
                    _log.warning("llm.circuit.reopened", key=key)
                else:
                    circuit.consecutive_failures += 1
                    if circuit.consecutive_failures >= self._failure_threshold:
                        circuit.state = CircuitState.OPEN
                        circuit.opened_at = time.monotonic()
                        _log.warning(
                            "llm.circuit.opened",
                            key=key,
                            consecutive_failures=circuit.consecutive_failures,
                        )
            raise

        async with circuit.lock:
            if circuit.state is CircuitState.HALF_OPEN:
                _log.info("llm.circuit.closed", key=key)
            circuit.state = CircuitState.CLOSED
            circuit.consecutive_failures = 0
        return result

    def state_of(self, key: str) -> CircuitState:
        """Diagnostic read of the current state (no async lock)."""
        circuit = self._circuits.get(key)
        return circuit.state if circuit else CircuitState.CLOSED


__all__ = ["CircuitBreaker", "CircuitState"]
