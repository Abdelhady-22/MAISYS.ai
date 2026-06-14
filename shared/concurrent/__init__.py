"""Concurrency helpers used by the ingestion pipelines.

Two primitives:

* ``gather_with_limit`` — like ``asyncio.gather``, but caps the number
  of coroutines running simultaneously via a semaphore.
* ``BatchProcessor[I, O]`` — processes a list of inputs in
  fixed-size batches with bounded concurrency, calling an
  ``on_progress`` callback after each item.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Generic, TypeVar

from shared.logger import get_logger

_log = get_logger(__name__)

T = TypeVar("T")
I = TypeVar("I")  # noqa: E741 — generic type-var name is conventional
O = TypeVar("O")  # noqa: E741


async def gather_with_limit(
    *coros: Awaitable[T],
    limit: int,
    return_exceptions: bool = False,
) -> list[T]:
    """Run ``coros`` with at most ``limit`` running concurrently.

    Semantics match ``asyncio.gather``: order of results matches order
    of inputs; ``return_exceptions=False`` raises on the first
    exception; ``True`` returns exceptions as ordinary elements.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    semaphore = asyncio.Semaphore(limit)

    async def _bounded(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(_bounded(c) for c in coros), return_exceptions=return_exceptions)  # type: ignore[return-value]


class BatchProcessor(Generic[I, O]):
    """Process inputs in batches with bounded concurrency.

    ``batch_size`` controls how many inputs are dispatched at a time.
    ``concurrency`` controls how many of the batch run simultaneously
    (defaults to ``batch_size``).

    ``on_progress(done, total)`` is invoked after each successful
    item. Failures still increment ``done`` so progress always
    advances — the exception is recorded in the result.
    """

    def __init__(
        self,
        process: Callable[[I], Awaitable[O]],
        *,
        batch_size: int = 10,
        concurrency: int | None = None,
        on_progress: (
            Callable[[int, int], None] | Callable[[int, int], Awaitable[None]] | None
        ) = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._process = process
        self._batch_size = batch_size
        self._concurrency = concurrency or batch_size
        self._on_progress = on_progress

    async def run(self, inputs: Iterable[I]) -> list[O | BaseException]:
        """Process every input, returning results in input order.

        Returns a list where each position is either the produced
        output ``O`` or the exception raised while processing that
        input. Callers decide whether to short-circuit on exceptions.
        """
        items = list(inputs)
        total = len(items)
        results: list[O | BaseException] = [None] * total  # type: ignore[list-item]
        done = 0

        for batch_start in range(0, total, self._batch_size):
            batch = items[batch_start : batch_start + self._batch_size]
            batch_results = await gather_with_limit(
                *(self._process(item) for item in batch),
                limit=self._concurrency,
                return_exceptions=True,
            )
            for offset, result in enumerate(batch_results):
                results[batch_start + offset] = result
                done += 1
                if self._on_progress is not None:
                    outcome = self._on_progress(done, total)
                    if asyncio.iscoroutine(outcome):
                        await outcome
        return results


__all__ = ["BatchProcessor", "gather_with_limit"]
