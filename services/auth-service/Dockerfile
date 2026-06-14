# syntax=docker/dockerfile:1.7
#
# auth-service production image.
#
# BUILD CONTEXT: MAISYS repo root (NOT services/auth-service).
# The image needs the shared/ monorepo modules which sit alongside
# services/auth-service. Build with:
#
#     docker build -f services/auth-service/Dockerfile -t maisys-auth:latest .
#
# Run locally (against a Postgres on the host):
#
#     docker run --rm -p 8000:8000 \
#         -e DATABASE_URL='postgresql+asyncpg://user:pass@host.docker.internal:5432/maisys' \
#         -e JWT_SECRET='change-me' \
#         maisys-auth:latest

# ─── Builder ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for native wheels (argon2-cffi, cryptography, asyncpg).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a virtualenv we can copy whole into the runtime image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY services/auth-service/requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt


# ─── Runtime ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    HOST=0.0.0.0 \
    PORT=8000

# Runtime libs only — libpq5 for asyncpg, ca-certs for HTTPS (OAuth JWKS).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --shell /sbin/nologin app

WORKDIR /app

# Bring in the prebuilt venv.
COPY --from=builder --chown=app:app /opt/venv /opt/venv

# Shared monorepo modules sit alongside the service; copy them in.
COPY --chown=app:app shared /app/shared

# Service code (main.py, routes/, services/, utils/, repository/, models/,
# exceptions/, alembic/, alembic.ini). The .dockerignore at the service
# folder strips tests/ and caches.
COPY --chown=app:app services/auth-service /app

USER app

EXPOSE 8000

# Healthcheck pings /health (added by main.py).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:8000/health || exit 1

# Tune workers via env (default 4 — adjust by container CPU shares).
CMD ["sh", "-c", "uvicorn main:app --host ${HOST} --port ${PORT} --workers ${UVICORN_WORKERS:-4}"]
