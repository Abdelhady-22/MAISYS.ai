# services/auth-service/

Identity, authentication, and authorization for MAISYS.

## Required Reading

- `docs/technical-guides/part3.md` §1 — auth-service spec
- `docs/technical-guides/part5.md` (auth schema) — Postgres tables for users, sessions, OAuth identities, OTP, RBAC
- `docs/technical-guides/part2.md` §3 — shared auth library (JWT decode used by all other services)
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- User registration (email + password)
- Email verification via OTP
- Login (password, OAuth Google, OAuth Apple)
- JWT issuance (access + refresh)
- Token refresh
- Password reset flow
- Profile management (name, language, locale, avatar)
- RBAC (roles: user, premium, admin, super_admin)
- Session management (active sessions, revoke)
- OTP for sensitive actions

## Endpoints

Roughly 12 endpoints (full list in Part 3 §1):

- `POST /auth/register` — create unverified account
- `POST /auth/verify-otp` — verify email OTP
- `POST /auth/login` — password login
- `POST /auth/oauth/{provider}/callback` — OAuth callback (google, apple)
- `POST /auth/refresh` — exchange refresh token
- `POST /auth/logout` — revoke session
- `POST /auth/password/reset/request`
- `POST /auth/password/reset/confirm`
- `GET /auth/me` — current user profile
- `PATCH /auth/me` — update profile
- `GET /auth/sessions` — list active sessions
- `DELETE /auth/sessions/{id}` — revoke specific session

## Tables (per Part 5)

- `users`
- `user_profiles`
- `oauth_identities`
- `sessions`
- `otp_codes`
- `password_resets`
- `roles`
- `user_roles`
- `audit_log`

## Security Rules

- Passwords hashed with Argon2id (never bcrypt, never plain SHA)
- JWT signed with HS256; secret from cloud Secret Manager
- Refresh tokens are opaque random strings (not JWTs), stored hashed
- All OTPs 6 digits, expire in 10 minutes, max 3 attempts then locked
- Rate limit on login: 5 per 15 min per IP, 10 per 15 min per email
- Account lock after 5 failed logins; unlocks via OTP
- All sensitive endpoints (`/me PATCH`, password reset, session revoke) audited

## Dependencies

- Postgres (own database `auth`)
- Redis (rate limits, OTP storage)
- notification-service (email + SMS for OTP)

## What This Service Does NOT Do

- No medical content access checks (that's per-service authorization based on the JWT claims this service issues)
- No business analytics
- No external identity provider beyond Google + Apple OAuth
