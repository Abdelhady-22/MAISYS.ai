# notification-service

Outbound email delivery for MAISYS — OTP codes, password resets, login
codes, export-ready alerts, beta review confirmations.

**Port:** 8009
**Own database:** `maisys_notification_db`
**Channels in v1:** **email only** (SendGrid). SMS + in-app deferred — see Scope below.

## Required reading

- `docs/technical-guides/part1.md` §7.10 — service catalog entry
- `docs/technical-guides/part5.md` §7 — complete specification (message format, templates, retry policy, security)
- `services/CLAUDE.md` — all-services standards

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness — verifies DB reachable |
| GET | `/metrics` | Prometheus scrape target |
| POST | `/notifications/send` | Accept a notification for async delivery (202) |
| GET | `/notifications/{id}` | Get the current status of a previously accepted notification |

Both `/notifications` endpoints require a valid JWT via `Authorization: Bearer <token>` (`shared/auth.get_current_user`).

### `POST /notifications/send`

Request body matches Part 5 §7.1 RabbitMQ message format exactly — the
HTTP body and a future queue payload share one schema so callers can
swap transports without changing field names.

```json
{
  "notification_type": "email_verify",
  "user_id": "user-uuid",
  "recipient_email": "user@example.com",
  "language": "en",
  "template_name": "email_verify",
  "template_vars": {
    "user_name": "Ahmad",
    "otp_code": "847291",
    "expires_in_minutes": 10
  },
  "correlation_id": "uuid-or-null",
  "priority": "high"
}
```

`notification_type` and `template_name` must match (we keep both for
queue-payload parity). Mismatch → 400 with `TEMPLATE_NAME_MISMATCH`.

Returns **202 Accepted** with:

```json
{
  "success": true,
  "data": {
    "notification_id": "32-char-uuid-hex",
    "status": "queued",
    "accepted_at": "2026-..."
  }
}
```

Delivery happens in a background task; the caller does **not** block.

### `GET /notifications/{notification_id}`

Returns the current status (`queued` / `delivering` / `delivered` /
`failed`), number of attempts, last error (if any), and timestamps.

## Templates (5, all bilingual)

Per Part 5 §7.2:

| Name | Subject (en) | Required vars |
|---|---|---|
| `email_verify` | Verify your MAISYS email address | `user_name`, `otp_code`, `expires_in_minutes` |
| `password_reset` | Reset your MAISYS password | `user_name`, `otp_code`, `expires_in_minutes` |
| `login_otp` | Your MAISYS login code | `otp_code`, `expires_in_minutes` |
| `export_ready` | Your MAISYS export is ready | `user_name`, `download_url` |
| `beta_session_reviewed` | Your MAISYS Beta feedback has been reviewed | `user_name` |

Templates are stored as Python constants in `services/template_renderer.py`.
For v1 this is simpler than file-based loading and lets type-checkers
catch mistakes earlier. Migration to a `templates/<name>.{en,ar}.{html,txt}`
file layout is a one-file change (the `render_email` function is the
only caller). Adding a new template requires both adding it to the
`TEMPLATES` dict AND extending the `NotificationType` Literal in
`models/schemas.py` — the coupling is deliberate.

## Retry policy

Per Part 5 §7.3: **3 retries with exponential backoff** — 60s, 300s,
1800s between attempts. Total of 4 attempts (1 + 3). After the last
attempt the row is marked `failed` and the error is recorded.

**Template / render errors are NOT retried** — those are caller bugs;
retrying won't fix them. The row is marked `failed` immediately and
the email adapter is never invoked.

## Scope — what's NOT in this PR

- **SMS channel** (Twilio) — deferred. Part 5 §7 lists email only;
  CLAUDE.md and brief extended to SMS but per "act by guides" we
  build email-only for v1. P3-C13.
- **In-app notifications** — deferred. Same reasoning. P3-C13.
- **SMTP fallback** — deferred. Part 5 §7.3 says "if SendGrid fails,
  fall back to SMTP for the retry attempt" — v1 retries via SendGrid
  only. P3-C15.
- **RabbitMQ queue consumer** — deferred. The HTTP body matches the
  queue payload field-for-field, so adopting the queue later is a
  thin wrapper around the existing `NotificationSender.accept()`
  method. P3-C16.
- **`notification_preferences` table** — deferred. Not in Part 1
  §7.10 or Part 5 §7; only in the per-service CLAUDE.md. P3-C14.
- **`suppression_list` table** — deferred for the same reason. P3-C14.
- **`in_app_notifications` table** — deferred (no in-app channel). P3-C14.

## Running locally

```bash
docker-compose up postgres notification-service
```

Then send a test email:

```bash
curl -X POST http://localhost:8009/notifications/send \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "notification_type": "login_otp",
    "user_id": "test-user",
    "recipient_email": "you@example.com",
    "language": "en",
    "template_name": "login_otp",
    "template_vars": {"otp_code": "123456", "expires_in_minutes": 10},
    "priority": "high"
  }'
```

## Tests

```bash
pytest services/notification-service/tests/
pytest services/notification-service/tests/ --cov=services/notification_service
```

27 tests. Source coverage ~92% (SendGrid integration path covered by
integration not unit). Critical paths (`notification_sender`,
`template_renderer`, `routes/notifications`) at 100%.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` / `production` / `test` |
| `LOG_LEVEL` | `INFO` | structlog level |
| `JWT_SECRET` | required | shared with auth-service |
| `CORS_ORIGINS` | `*` | comma-separated allow list |
| `ENABLE_METRICS` | `true` | mount `/metrics` |
| `ENABLE_WIRING` | `true` | disable lifespan wiring in tests |
| `DATABASE_URL` | (compose default) | `postgresql+asyncpg://...` |
| `SENDGRID_API_KEY` | required for prod | from SendGrid dashboard |
| `EMAIL_FROM` | `no-reply@maisys.io` | sender address |
