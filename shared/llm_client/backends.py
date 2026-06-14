"""Backend protocol and implementations for the LLM client.

The ``Backend`` protocol abstracts the actual LLM call so the client
can switch between LiteLLM (production) and ``FakeLLMBackend`` (tests)
without changing call sites.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from shared.llm_client.types import CompletionRequest, CompletionResponse, Usage
from shared.logger import get_logger

_log = get_logger(__name__)


@runtime_checkable
class Backend(Protocol):
    """Minimal async backend the LLM client expects."""

    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    def stream(self, request: CompletionRequest) -> AsyncIterator[str]: ...


class LiteLLMBackend:
    """Production backend that routes through LiteLLM's unified API.

    LiteLLM is imported lazily so test environments without the package
    don't fail on import. ``litellm.acompletion`` is the async entry
    point; the response shape is normalised across providers.
    """

    def __init__(self) -> None:
        import importlib

        self._litellm = importlib.import_module("litellm")

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        start = time.monotonic()
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
                for m in request.messages
            ],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            kwargs["response_format"] = request.response_format
        if request.tools is not None:
            kwargs["tools"] = list(request.tools)

        raw = await self._litellm.acompletion(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = raw["choices"][0]
        message = choice["message"]
        content: str = message.get("content") or ""
        tool_calls = message.get("tool_calls")
        finish_reason = choice.get("finish_reason")
        usage_raw = raw.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
        )
        cost_usd = self._safe_cost(raw)

        return CompletionResponse(
            content=content,
            model=request.model,
            usage=usage,
            latency_ms=latency_ms,
            cached=False,
            finish_reason=finish_reason,
            tool_calls=tuple(tool_calls) if tool_calls else None,
            cost_usd=cost_usd,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
                for m in request.messages
            ],
            "temperature": request.temperature,
            "stream": True,
        }
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        async for chunk in await self._litellm.acompletion(**kwargs):
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                yield content

    def _safe_cost(self, raw: dict[str, Any]) -> float | None:
        """LiteLLM exposes per-call cost when available; fall back to None."""
        try:
            return float(self._litellm.completion_cost(raw))
        except Exception:
            return None


# ─── Fake backend for tests ────────────────────────────────────────


@dataclass
class FakeResponse:
    """One scripted response the fake backend will return."""

    content: str
    prompt_tokens: int = 10
    completion_tokens: int = 20
    finish_reason: str = "stop"
    raise_exc: BaseException | None = None


class FakeLLMBackend:
    """Deterministic backend for tests.

    Usage:
        backend = FakeLLMBackend()
        backend.queue(FakeResponse(content="hi"))
        # one call -> returns 'hi'. queue is FIFO.

    Or set ``responder`` to a callable that derives the response from
    the request.
    """

    def __init__(
        self,
        responder: Callable[[CompletionRequest], FakeResponse] | None = None,
    ) -> None:
        self._queue: list[FakeResponse] = []
        self._responder = responder
        self.calls: list[CompletionRequest] = []

    def queue(self, response: FakeResponse) -> None:
        self._queue.append(response)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls.append(request)
        if self._responder is not None:
            scripted = self._responder(request)
        elif self._queue:
            scripted = self._queue.pop(0)
        else:
            scripted = FakeResponse(content="(fake response)")
        if scripted.raise_exc is not None:
            raise scripted.raise_exc
        return CompletionResponse(
            content=scripted.content,
            model=request.model,
            usage=Usage(
                prompt_tokens=scripted.prompt_tokens,
                completion_tokens=scripted.completion_tokens,
                total_tokens=scripted.prompt_tokens + scripted.completion_tokens,
            ),
            latency_ms=1,
            cached=False,
            finish_reason=scripted.finish_reason,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        response = await self.complete(request)
        for chunk in response.content.split(" "):
            yield chunk + " "


__all__ = ["Backend", "FakeLLMBackend", "FakeResponse", "LiteLLMBackend"]
