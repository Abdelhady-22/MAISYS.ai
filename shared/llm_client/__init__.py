"""LiteLLM-based LLM client with Redis cache and per-model circuit breaker.

Public exports:

* ``LLMClient`` — top-level facade. ``LLMClient.from_env()`` for prod.
* ``CompletionRequest`` / ``CompletionResponse`` / ``Message`` /
  ``Usage`` — request/response shapes.
* ``FakeLLMBackend`` / ``FakeResponse`` — for tests.
* ``CircuitBreaker`` / ``CircuitState`` — breaker primitives, exposed
  for advanced users (e.g. sharing a breaker across clients).
* ``LLMCache`` / ``InMemoryCacheBackend`` — cache primitives.

Required env vars (production):
* ``LLM_CACHE_REDIS_URL`` (optional; enables caching when set)
* ``LLM_CACHE_TTL_SECONDS`` (default 3600)
* ``LLM_BREAKER_FAILURE_THRESHOLD`` (default 5)
* ``LLM_BREAKER_COOLDOWN_SECONDS`` (default 60.0)
* Provider-specific (consumed by LiteLLM): ``OPENAI_API_KEY``,
  ``AZURE_API_KEY``, ``ANTHROPIC_API_KEY``, etc.
"""

from shared.llm_client.backends import (
    Backend,
    FakeLLMBackend,
    FakeResponse,
    LiteLLMBackend,
)
from shared.llm_client.cache import (
    CacheBackend,
    InMemoryCacheBackend,
    LLMCache,
    cache_key,
)
from shared.llm_client.circuit_breaker import CircuitBreaker, CircuitState
from shared.llm_client.client import LLMClient
from shared.llm_client.types import (
    CompletionRequest,
    CompletionResponse,
    Message,
    Role,
    Usage,
)

__all__ = [
    "Backend",
    "CacheBackend",
    "CircuitBreaker",
    "CircuitState",
    "CompletionRequest",
    "CompletionResponse",
    "FakeLLMBackend",
    "FakeResponse",
    "InMemoryCacheBackend",
    "LLMCache",
    "LLMClient",
    "LiteLLMBackend",
    "Message",
    "Role",
    "Usage",
    "cache_key",
]
