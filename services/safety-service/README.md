# safety-service

The safety guardrail every other MAISYS module consults. Detects medical
emergencies in free text and wraps service responses with profile-aware
warnings and a bilingual educational disclaimer.

**Port:** 8008
**Stateless** — no Postgres, no Alembic, no repository layer.

## Required reading

- `docs/technical-guides/part1.md` §7.9 — service catalog entry
- `docs/technical-guides/part5.md` §5 — complete specification (algorithm, keyword lists, response payload shape, API contracts)
- `services/CLAUDE.md` — all-services standards

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe |
| GET | `/metrics` | Prometheus scrape target |
| POST | `/safety/check` | Detect emergency indicators in user input |
| POST | `/safety/wrap` | Wrap a service response with profile warnings and disclaimer |

Both `/safety/check` and `/safety/wrap` require a valid JWT via
`Authorization: Bearer <token>`. JWT validation uses `shared/auth`.

### `POST /safety/check`

Request body matches Part 5 §5.5:

```json
{
  "text": "I have been having chest pain",
  "language": "en",
  "session_id": "uuid-or-null"
}
```

Response — emergency:

```json
{
  "success": true,
  "data": {
    "is_emergency": true,
    "severity": "critical",
    "detected_pattern": "chest_pain",
    "category": "cardiac",
    "detection_stage": "stage_1",
    "emergency_response": {
      "title_en": "⚠️ This may be a medical emergency",
      "title_ar": "⚠️ قد تكون هذه حالة طوارئ طبية",
      "message_en": "...",
      "message_ar": "...",
      "actions_en": ["Call emergency services...", "..."],
      "actions_ar": ["...", "..."],
      "do_not_wait": true,
      "session_should_halt": true
    }
  }
}
```

Response — safe:

```json
{"success": true, "data": {"is_emergency": false}}
```

### `POST /safety/wrap`

Calling services post their planned response plus the user's profile.
Returns a `ProfileWarning` list (pregnancy alerts etc.) plus the
standard bilingual disclaimer. The wrapped content itself is returned
**unchanged** — safety-service never rewrites the medical text. See
Part 5 §5.5 for the full request/response shape.

## Detection algorithm

Two stages per Part 5 §5.1:

1. **Stage 1 — fast regex** on normalised input against compiled
   English + Arabic patterns from §5.2. Match → emergency, return
   immediately. Latency ~1ms.
2. **Stage 1.5 — ambiguous patterns** (curated subset that may match
   in non-emergency contexts e.g. "I read about chest pain"). Match
   → continue to Stage 2 if enabled, otherwise safe verdict.
3. **Stage 2 — LLM confirmation** (opt-in). Cheap fast LLM judges
   "Is this a current emergency? YES/NO". Timeout → safe.

Stage 2 is **disabled by default** — see decision log P3-C04.

## Pregnancy warning rules

Curated set of 11 high-risk drugs (5 Cat-X + 6 Cat-D) with bilingual
warning messages. Fires only when:
1. `user_profile.is_pregnant == true`, AND
2. `context` is one of `drug_profile` / `drug_interaction` / `drug_dosage`, AND
3. `drug_names` contains a known drug.

A chatbot answer that mentions ibuprofen in passing does NOT trigger
a warning — drug context is required.

## Running locally

```bash
# From the repo root
docker-compose up safety-service
```

Then:

```bash
curl -X POST http://localhost:8008/safety/check \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"text":"I have chest pain","language":"en"}'
```

## Tests

```bash
pytest services/safety-service/tests/
pytest services/safety-service/tests/ --cov=services/safety_service
```

77 tests. Source coverage ~95%. Critical paths (emergency detection,
pregnancy rules) at 97-100%.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` / `production` / `test` |
| `LOG_LEVEL` | `INFO` | structlog level |
| `JWT_SECRET` | required | shared with auth-service |
| `CORS_ORIGINS` | `*` | comma-separated allow list |
| `ENABLE_METRICS` | `true` | mount `/metrics` |
| `SAFETY_LLM_CONFIRM_ENABLED` | `false` | enable Stage 2 LLM |
| `SAFETY_STAGE_2_MODEL` | `openai/gpt-4o-mini` | when Stage 2 enabled |
| `SAFETY_STAGE_2_TIMEOUT_SECONDS` | `5.0` | hard cap on Stage 2 call |
| `OPENAI_API_KEY` | — | required when Stage 2 enabled |
| `LLM_CACHE_REDIS_URL` | — | shared/llm_client cache, when Stage 2 enabled |

## What this service does NOT do

- No emergency response coordination — it tells the user to seek care.
- No location tracking.
- No persistent state across requests.
- No content moderation in the social-media sense.
- No drug interactions — that's drug-service. Calling services
  consult both: drug-service for the medical content, safety-service
  for the safety wrap.
