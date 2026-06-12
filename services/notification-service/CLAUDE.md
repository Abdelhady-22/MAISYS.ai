# services/notification-service/

Email (SendGrid), SMS (Twilio), and in-app notifications.

## Required Reading

- `docs/technical-guides/part2.md` §8 — notification-service spec
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- Send email (transactional + occasional digest)
- Send SMS (OTP, password reset, critical alerts)
- Persist in-app notifications (delivered via WebSocket from api-gateway)
- Template management (bilingual)
- Delivery retry with exponential backoff
- Suppression list (bounces, unsubscribes)
- Per-user notification preferences

## Endpoints (Internal — Not Exposed Through Gateway)

- `POST /notify/email` — send email (used by auth-service for OTP, etc.)
- `POST /notify/sms` — send SMS
- `POST /notify/in-app` — create in-app notification
- `GET /notify/preferences/{user_id}` — get user prefs
- `PATCH /notify/preferences/{user_id}` — update prefs (forwarded from frontend via gateway → auth → notify)

## Template System

- Templates in `services/notification-service/templates/`
- One file per template per language: `otp_email.en.html`, `otp_email.ar.html`
- Jinja2 with strict variable validation
- Bilingual subjects, bodies, plain-text alternatives
- Never inject user input as HTML (always escape)

## Async Delivery

- Direct API call to SendGrid/Twilio is sync from the service's perspective, but the caller (auth-service, etc.) calls notify async via RabbitMQ
- Queue: `notifications.email`, `notifications.sms`, `notifications.in_app`
- Retry: 3 attempts with exponential backoff (1s, 5s, 30s); after that, dead-letter queue + alert

## Tables (per Part 5)

- `notification_log` (every send attempt)
- `notification_preferences`
- `suppression_list` (bounced/unsubscribed addresses)
- `in_app_notifications` (delivered + read state)

## Dependencies

- Postgres (own database `notification`)
- Redis (rate limit per recipient — prevent spam)
- RabbitMQ (consume queue)
- SendGrid API (email)
- Twilio API (SMS)

## What This Service Does NOT Do

- No marketing emails (out of scope; if added later, separate service)
- No push notifications (mobile app is out of scope for v1)
- No phone calls (Twilio Voice unused)
