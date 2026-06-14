"""LLM client request and response types.

The shapes below are the public contract every backend implements,
including the test fake. Keeping them in a leaf module avoids circular
imports between ``client.py``, ``backends.py``, and ``cache.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    """One entry in the chat-completion conversation."""

    role: Role
    content: str
    name: str | None = None


@dataclass(frozen=True)
class CompletionRequest:
    """Input to ``LLMClient.complete()`` / ``stream()``.

    ``model`` follows LiteLLM's ``provider/model`` convention
    (``openai/gpt-4o-mini``, ``anthropic/claude-3-5-sonnet-20241022``,
    ``azure/maisys-gpt4``). The circuit breaker keys on this string.
    """

    model: str
    messages: tuple[Message, ...]
    temperature: float = 0.2
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None
    tools: tuple[dict[str, Any], ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    """Token accounting from the provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class CompletionResponse:
    """Output of ``LLMClient.complete()``."""

    content: str
    model: str
    usage: Usage
    latency_ms: int
    cached: bool = False
    finish_reason: str | None = None
    tool_calls: tuple[dict[str, Any], ...] | None = None
    cost_usd: float | None = None


__all__ = ["CompletionRequest", "CompletionResponse", "Message", "Role", "Usage"]
