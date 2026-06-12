# services/admin-service/

Admin dashboard backend. Internal-facing.

## Required Reading

- `docs/technical-guides/part3.md` §14 — admin-service spec
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- User management (list, search, role assignment, suspend/unsuspend, deletion requests)
- Content moderation (flag review, manual override)
- Beta consent audit
- Aggregate metrics views (signups, MAU, module usage, cost per user)
- Audit log search across services
- Feature flag management
- System announcements (banner-style notifications to all users)

## Endpoints

All endpoints require `admin` or `super_admin` role (enforced by gateway + verified here).

- `GET /admin/users` — paginated list with filters
- `GET /admin/users/{id}` — full user record + activity summary
- `PATCH /admin/users/{id}/role` — change role (super_admin only)
- `POST /admin/users/{id}/suspend`
- `POST /admin/users/{id}/restore`
- `DELETE /admin/users/{id}` — GDPR-style deletion (purges across services)
- `GET /admin/flags` — content moderation flags queue
- `PATCH /admin/flags/{id}` — moderate a flag
- `GET /admin/metrics/summary` — top-line metrics
- `GET /admin/audit` — cross-service audit search
- `GET /admin/feature-flags` — list current flags
- `PATCH /admin/feature-flags/{name}` — toggle flag
- `POST /admin/announcements` — create banner

## Cross-Service User Deletion

User deletion is the most complex flow. When a user is deleted:

1. admin-service publishes `user.deleted` event to RabbitMQ
2. Each service subscribes and purges its data:
   - auth-service: drop user row + cascades
   - chatbot-service: delete sessions + messages
   - drug-service: delete query history
   - research-service: delete uploads + per-user Qdrant collection
   - export-service: delete generated PDFs
   - notification-service: delete preferences + suppression entries
3. Each service publishes `user.deletion.complete` for that service
4. admin-service tracks completion across all services
5. Final confirmation logged once all services report complete

Deletion is irreversible after a 30-day grace period (during which an admin can restore via `POST /admin/users/{id}/restore` if requested).

## Tables (per Part 5)

- `admin_actions` (audit of every admin action)
- `feature_flags`
- `announcements`
- `deletion_requests` (state machine across cross-service deletion)

## Dependencies

- Postgres (own database `admin`)
- RabbitMQ (publish deletion events)
- All other services (via HTTP for some lookups, via events for state changes)

## What This Service Does NOT Do

- No customer-facing functionality (admin only)
- No PII surfacing beyond what's necessary (data shown to admins is access-logged)
- No write access to other services' data (only event-driven coordination, never direct DB access)
