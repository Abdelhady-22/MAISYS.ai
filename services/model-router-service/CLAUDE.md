# services/model-router-service/

Centralized LLM routing. The only service that talks to LLM providers directly.

## Required Reading

- `docs/technical-guides/part2.md` §5 — model-router-service spec
- `docs/technical-guides/part6.md` §5 — LLM client patterns (retry, circuit breaker, KV cache)
- `services/CLAUDE.md` — all-services standards

## Why a Separate Service

Putting LLM access behind one service gives us:

- **Cost visibility** — all token spend in one place, easy to budget per-team/per-feature
- **KV cache hits** — a centralized cache catches more reuse than per-service caches
- **Provider fallback** — if OpenAI is down, requests reroute to Anthropic transparently
- **A/B routing** — easy to send % of traffic to vLLM Beta for evaluation
- **Rate limit pooling** — one tenant's spike doesn't break others

## Endpoints (Internal — Not Exposed Through Gateway)

- `POST /llm/chat` — chat completion (system + messages + tools optional)
- `POST /llm/stream` — streaming chat completion (Server-Sent Events)
- `POST /llm/embed` — generate embedding (passthrough to embedding model)
- `GET /llm/models` — list available models with status
- `GET /llm/stats/{request_id}` — token usage + cost for a request

## Routing Strategy

Per request, the router picks a model based on:

1. **Caller's tier hint** — `cheap`, `default`, `premium`, `beta`
2. **Capability needed** — function calling, vision, long context, Arabic strength
3. **Provider health** — circuit breaker state per provider
4. **Cost budget** — if monthly budget exceeded for non-essential tier, downgrade

```python
# Caller side
response = await llm_client.chat(
    messages=[...],
    tier="cheap",                  # cheap | default | premium | beta
    capability=["function_calling"],
    max_tokens=500,
)
```

The router resolves "cheap" to a specific provider+model at request time.

## Providers Configured

- **OpenAI** — GPT-4o, GPT-4o-mini
- **Anthropic** — Claude 3.5 Sonnet, Claude 3.5 Haiku
- **Google AI** — Gemini 2.0 Flash, Gemini 1.5 Pro
- **DeepSeek** — DeepSeek V3 (cheap tier preferred)
- **vLLM (self-hosted)** — MAISYS Beta model (beta tier only)

Provider config in cloud Secret Manager. API keys never leave this service.

## KV Cache & Prefix Cache

Per Part 6 §5:

- **KV cache**: full prompt → response cache, Redis, key = SHA256(model + messages + tools + temperature), TTL 24h
- **Prefix cache**: common prefixes (system prompts) precomputed by vLLM for the Beta model

Cache hit returns instantly. Cache miss goes to provider, then writes to cache before returning.

## Retry & Circuit Breaker

- 3 retries per provider call, exponential backoff (1s, 4s, 16s)
- Circuit breaker per provider: open after 5 consecutive 5xx or timeouts, half-open after 60s, closed after 1 successful call
- When circuit open, requests reroute to next-best provider for the requested tier

## Tables (per Part 5)

- `llm_requests` (audit: request_id, caller_service, model, tokens_in, tokens_out, cost_cents, latency_ms, cache_hit)
- `provider_health_log`

## Dependencies

- Redis (KV cache)
- Postgres (own database `model_router`)
- LiteLLM (provider abstraction library)
- vLLM server (internal cluster endpoint)
- External: OpenAI, Anthropic, Google AI, DeepSeek

## What This Service Does NOT Do

- No prompt engineering. Callers send the prompts; this service routes them.
- No business logic of any kind.
- No persistence of message content beyond the audit row (and that's hashed for sensitive content).
