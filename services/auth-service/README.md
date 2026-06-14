# auth-service

MAISYS authentication & authorisation service. Handles user
registration, login, OAuth (Google / Apple), JWT issuance and
rotation, session management, and password reset.

## Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| POST   | `/auth/register`                       | Create an account; sends email-verify OTP                 | — |
| POST   | `/auth/verify-otp`                     | Verify email OTP **or** complete admin-login OTP           | — |
| POST   | `/auth/login`                          | Authenticate. Returns tokens OR an `otp_required` shape if the role triggers the OTP gate | — |
| POST   | `/auth/refresh`                        | Rotate refresh token; returns new access + refresh         | — |
| POST   | `/auth/logout`                         | Revoke the current session (idempotent)                    | Bearer |
| POST   | `/auth/oauth/{provider}/callback`      | Exchange a Google / Apple ID token for MAISYS tokens       | — |
| POST   | `/auth/password/reset/request`         | Request a reset email (always 200 — no enumeration)        | — |
| POST   | `/auth/password/reset/confirm`         | Consume the reset token and set a new password             | — |
| GET    | `/auth/me`                             | Current user's profile                                     | Bearer |
| PATCH  | `/auth/me`                             | Update profile (email change triggers re-verification)     | Bearer |
| GET    | `/auth/sessions`                       | List active sessions for the current user                  | Bearer |
| DELETE | `/auth/sessions/{id}`                  | Revoke a specific session                                  | Bearer |
| GET    | `/health`                              | Liveness probe                                             | — |
| GET    | `/ready`                               | Readiness probe                                            | — |
| GET    | `/metrics`                             | Prometheus metrics                                         | — |
| GET    | `/docs`, `/redoc`                      | OpenAPI UI                                                  | — |

All responses use the shared `APIResponse[T]` envelope: `{success, data?, error?}`.
Errors translate to `{ "success": false, "error": { "code": "X", "message": "Y", "details": {} } }`.

## Local development

### Option A — bare-metal Python

```bash
cd services/auth-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=../..:. \
    DATABASE_URL='sqlite+aiosqlite:///./dev.db' \
    JWT_SECRET='dev-secret' \
    python main.py
```

Visit <http://localhost:8000/docs>.

Run Alembic migrations against the dev DB:

```bash
PYTHONPATH=../..:. DATABASE_URL='sqlite+aiosqlite:///./dev.db' alembic upgrade head
```

### Option B — docker-compose (Postgres included)

```bash
docker compose -f services/auth-service/docker-compose.dev.yml up --build
```

This brings up Postgres + a one-shot migration runner + the service on
<http://localhost:8001>.

## Running tests

```bash
cd services/auth-service
PYTHONPATH=../..:. python -m pytest tests/ --asyncio-mode=auto -q
```

* **Unit tests** (`tests/repository/`, `tests/utils/`, `tests/services/`,
  `tests/routes/`) — fast, run against in-memory SQLite via the
  `db_session` fixture in `tests/conftest.py`.
* **Integration tests** (`tests/integration/`) — exercise the REAL
  `main.app` (CORS, middleware, exception handlers, all routers) with
  the DB dependency overridden onto the same SQLite session.

Test count at last gate run: **171 passing** (94 foundation + 36
service-layer + 34 route-layer + 7 integration).

Quality gates run on every commit: ruff, black (line-length 100),
mypy `--ignore-missing-imports --strict`, pytest.

## Environment variables

| Variable | Default | Required | Notes |
|---|---|---|---|
| `DATABASE_URL` | — | ✅ | SQLAlchemy async URL. Postgres: `postgresql+asyncpg://...`; SQLite: `sqlite+aiosqlite://...` |
| `JWT_SECRET`  | — | ✅ | Symmetric secret for HS256 access tokens |
| `JWT_ISSUER`  | `maisys` |   | `iss` claim on issued tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` |  | Access-token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | `30` |  | Refresh-token TTL |
| `OTP_EXPIRE_MINUTES`          | `10` |  | OTP code lifetime |
| `OTP_MAX_ATTEMPTS`            | `3`  |  | Wrong-OTP attempts before invalidation |
| `LOGIN_MAX_FAILED_ATTEMPTS`   | `5`  |  | Bad-password attempts before account lockout |
| `LOGIN_OTP_REQUIRED_ROLES`    | `admin,super_admin` | | Comma-separated roles that trigger the login OTP gate |
| `PASSWORD_RESET_TTL_MINUTES`  | `30` |  | Reset-token lifetime |
| `GOOGLE_OAUTH_CLIENT_ID`      | — | for Google callbacks | `aud` claim verified on Google ID tokens |
| `APPLE_OAUTH_CLIENT_ID`       | — | for Apple callbacks  | `aud` claim verified on Apple ID tokens |
| `CORS_ORIGINS`                | `*` |  | Comma-separated origins, or `*` |
| `RATE_LIMIT_ENABLED`          | `true` |  | Set `false` in tests; turns slowapi off |
| `RATE_LIMIT_DEFAULT`          | `100/minute` |  | Global rate limit (per IP) |
| `LOG_LEVEL`                   | `INFO` |  | structlog level |
| `APP_ENV`                     | `production` |  | `development` enables uvicorn reload |
| `HOST`, `PORT`                | `0.0.0.0`, `8000` |  | Bind config |
| `UVICORN_WORKERS`             | `4` |  | Process pool size (Dockerfile CMD) |

## Migrations

Alembic config lives at `alembic.ini` + `alembic/`. Standard workflow:

```bash
# Create a new migration after model changes
PYTHONPATH=../..:. DATABASE_URL='...' alembic revision --autogenerate -m "describe"

# Apply pending migrations
PYTHONPATH=../..:. DATABASE_URL='...' alembic upgrade head

# Roll back one revision
PYTHONPATH=../..:. DATABASE_URL='...' alembic downgrade -1
```

The initial migration (`0001_initial_auth_schema.py`) creates all 9
tables: `users`, `user_profiles`, `sessions`, `otp_codes`,
`password_resets`, `oauth_accounts`, `audit_logs`, plus
SQLAlchemy / Alembic version tables.

## Production deployment

The Dockerfile is built from the **MAISYS repo root** so it can copy
the `shared/` monorepo modules:

```bash
docker build -f services/auth-service/Dockerfile -t maisys-auth:latest .
```

The image:
* runs as a non-root `app` user (uid 1000)
* exposes port 8000
* has a `HEALTHCHECK` that pings `/health` every 30s
* defaults to 4 uvicorn workers (`UVICORN_WORKERS` env)

To integrate with the root `docker-compose.yml`, add an `auth-service`
service block pointing at this Dockerfile with `build.context: .` and
`build.dockerfile: services/auth-service/Dockerfile`. See
`docker-compose.dev.yml` in this folder for a complete reference.

## Security notes

* Passwords are hashed with Argon2id (`argon2-cffi` defaults).
* OTP codes are SHA-256 hashed at rest.
* Refresh tokens are 32-byte random, stored as SHA-256 hash.
* Refresh reuse is treated as compromise: all sessions for the user
  are revoked.
* Email enumeration is prevented on `/auth/password/reset/request`
  and on `/auth/login` (same `INVALID_CREDENTIALS` code for unknown
  email and bad password).
* `/auth/sessions/{id}` for a session belonging to another user
  returns `SESSION_NOT_FOUND` (same as "doesn't exist") to avoid
  cross-user session enumeration.
* All sensitive fields (`password`, `secret`, `token`, `api_key`,
  `authorization`, `cookie`, `private_key`) are scrubbed from logs by
  `shared.logger.scrub_sensitive`.

## Architecture

```
        ┌──────────────────────────────┐
HTTP →  │  routes/  (FastAPI APIRouters)│
        │  – thin: parse, call, wrap   │
        └────────────┬─────────────────┘
                     │
        ┌────────────▼─────────────────┐
        │  services/  (business logic) │
        │  – orchestration, validation │
        │  – owns commit boundaries    │
        └────────────┬─────────────────┘
                     │
        ┌────────────▼─────────────────┐
        │  repository/  (SQL access)   │
        │  – one repo per table        │
        └────────────┬─────────────────┘
                     │
        ┌────────────▼─────────────────┐
        │  models/  (ORM + Pydantic)   │
        └──────────────────────────────┘
```

Routes don't touch repositories. Services don't touch HTTP.
Repositories don't compose business rules.

## License

MAISYS project — internal.
