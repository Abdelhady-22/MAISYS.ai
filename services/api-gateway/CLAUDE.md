# services/api-gateway/

The single entry point for all client traffic. Sits in front of every other service.

## Required Reading

- `docs/technical-guides/part1.md` §3 — request lifecycle
- `docs/technical-guides/part3.md` §0 — gateway routing table
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- **HTTP routing** to all 12 backend services by URL prefix (`/api/v1/auth/*` → auth-service, `/api/v1/drug/*` → drug-service, etc.)
- **WebSocket multiplexing** — one WebSocket connection from the client; gateway routes messages by `service` field to upstream service WebSockets
- **Auth verification** — decodes JWT, attaches `user_id` + `role` to forwarded request headers
- **Rate limiting** — per-user, per-endpoint, via Redis sliding window
- **Request logging** — single `request_id` generated here, propagated through `X-Request-ID` to all downstream services
- **CORS** — allow only configured frontend origins
- **Compression** — gzip responses
- **Health aggregation** — `/healthz` returns gateway + last-known status of upstreams

## What This Service Does NOT Do

- No business logic. Not one line.
- No database. The gateway has no Postgres.
- No LLM calls.
- No data transformation beyond header manipulation.

If a routing decision requires reading user data, the gateway forwards the request and lets the downstream service handle it. The gateway only knows: *is this token valid?* and *which service handles this URL?*

## Routing Table

| Path prefix | Upstream service |
|---|---|
| `/api/v1/auth/*` | auth-service |
| `/api/v1/chatbot/*` | chatbot-service |
| `/api/v1/drug/*` | drug-service |
| `/api/v1/symptom/*` | symptom-service |
| `/api/v1/lab/*` | lab-service |
| `/api/v1/research/*` | research-service |
| `/api/v1/translate/*` | translation-service |
| `/api/v1/export/*` | export-service |
| `/api/v1/notify/*` | notification-service |
| `/api/v1/admin/*` | admin-service |
| `/ws` | WebSocket multiplexer (routes by message `service` field) |

## Implementation Notes

- Stack: FastAPI + httpx (async forward proxy) + websockets library
- No long-lived state — gateway pods are interchangeable, scale horizontally
- Circuit breaker per upstream — open after 5 consecutive 5xx, half-open after 30s
- Request body forwarded as stream when possible (large file uploads to research-service)

## Public Endpoints

Apart from forwarding, the gateway exposes:

- `GET /healthz` — gateway alive
- `GET /readyz` — gateway alive + at least N% upstreams reachable
- `GET /metrics` — Prometheus
