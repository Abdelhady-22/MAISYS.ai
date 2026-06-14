# translation-service

Arabic ↔ English translation for all MAISYS services. Stateless,
medical-aware, three configurable modes.

**Port:** 8007
**Stateless** — Redis cache only, no Postgres.

## Required reading

- `docs/technical-guides/part1.md` §7.7 — service catalog entry
- `services/CLAUDE.md` — all-services standards

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness — reports which modes are wired |
| GET | `/metrics` | Prometheus scrape target |
| POST | `/translate` | Translate a single text |
| POST | `/translate/batch` | Translate up to 50 texts concurrently |

Both `/translate` endpoints require a JWT via `Authorization: Bearer <token>`.

### `POST /translate`

```json
{
  "text": "I have chest pain",
  "source_lang": "auto",
  "target_lang": "ar",
  "mode": "google",
  "style": "general"
}
```

* `source_lang`: `"ar"` / `"en"` / `"auto"` (detect by Arabic Unicode presence)
* `target_lang`: `"ar"` / `"en"`
* `mode`: `"google"` (default) / `"local"` / `"llm"`
* `style`: `"general"` / `"clinical"` / `"conversational"` — used only by LLM mode

Response:

```json
{
  "success": true,
  "data": {
    "translated_text": "...",
    "source_lang_detected": "en",
    "target_lang": "ar",
    "mode_used": "google",
    "cached": false
  }
}
```

### `POST /translate/batch`

Up to 50 items. Each item runs concurrently. Partial failures don't
abort the batch — failed items have `error` set, successful items
have the translated payload.

## Translation modes

Per Part 1 §7.7:

| Mode | Provider | Notes |
|---|---|---|
| `google` | Google Cloud Translation v2 REST | API key. Default. Best general-purpose quality. |
| `local` | `deep-translator` library | No API key. Wraps Google's public endpoint. Quality similar for short text. |
| `llm` | shared/llm_client (configurable LLM) | Recommended for medical terminology. Style-aware. |

A mode that isn't configured at startup raises `TranslationModeUnavailable`
on first use (HTTP 503). `/readyz` reports which modes are wired so
operators can spot misconfiguration immediately.

### LLM mode style guidance

| Style | When to use |
|---|---|
| `general` | Default — natural everyday phrasing |
| `clinical` | Patient-education register — accurate, neutral, accessible |
| `conversational` | Warm chatbot register — short sentences |

The system prompt always instructs the model to preserve generic drug
names in English (e.g. "warfarin" stays "warfarin" mid-Arabic
sentence) and to preserve numeric values and dosing schedules exactly.

## Cache

Per Part 1 §7.7: Redis, 24-hour TTL. Cache key is SHA-256 of:

```
source_lang | target_lang | mode | style | text
```

Mode and style are part of the key — a `llm/clinical` translation
won't collide with a `google` translation of the same text.

In tests / when `REDIS_URL` is not set, an in-memory cache is used
(no TTL eviction — process-bound lifetime).

## Language detection (when `source_lang="auto"`)

Deterministic: if any Arabic Unicode character is present in the
text, the source is detected as `"ar"`; otherwise `"en"`. Mixed-text
input always detects as `"ar"` — the meaningful clinical content is
the Arabic part and translating to English is the typical caller
need.

## Running locally

```bash
docker-compose up redis translation-service
```

```bash
curl -X POST http://localhost:8007/translate \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Take this medication twice daily with food",
    "target_lang": "ar",
    "mode": "llm",
    "style": "clinical"
  }'
```

## Tests

```bash
pytest services/translation-service/tests/
pytest services/translation-service/tests/ --cov=services/translation_service
```

38 tests. Source coverage ~85%, critical paths
(`translation_service`, `mode_selector`, `lang_detector`) at 98-100%.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | env name |
| `LOG_LEVEL` | `INFO` | structlog level |
| `JWT_SECRET` | required | shared with auth-service |
| `CORS_ORIGINS` | `*` | comma-separated allow list |
| `REDIS_URL` | (unset) | cache backend; in-memory fallback if unset |
| `GOOGLE_TRANSLATE_API_KEY` | (unset) | enables `google` mode |
| `OPENAI_API_KEY` | (unset) | one possible LLM provider; whatever shared/llm_client uses |

## What this service does NOT do

- **No language other than Arabic ↔ English** — Part 1 §7.7 scope.
- **No language detection beyond Arabic-vs-English** — no MSA-dialect
  detection, no script-mixed handling.
- **No transliteration** — cut from scope per the per-service CLAUDE.md.
- **No medical-glossary CRUD endpoints** — Part 1 §7.7 doesn't list a
  glossary table; medical terminology is handled by the LLM mode's
  preservation rule. P3-C18.
