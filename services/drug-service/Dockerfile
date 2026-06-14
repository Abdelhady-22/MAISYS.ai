# syntax=docker/dockerfile:1.7

# ── build stage ───────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /build

# Install build deps + shared library
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy shared lib first (rebuilt rarely)
COPY shared /build/shared

# Copy service requirements
COPY services/drug-service/requirements.txt /build/drug-requirements.txt

# Install both — shared deps via shared/requirements.txt then service-specific
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r /build/shared/requirements.txt \
    && pip install --no-cache-dir -r /build/drug-requirements.txt

# ── runtime stage ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user
RUN groupadd --system maisys && useradd --system --gid maisys --uid 1000 maisys

# Postgres client libs (asyncpg only needs libpq at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from build stage
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

WORKDIR /app

# Copy source — shared library + drug-service
COPY --chown=maisys:maisys shared /app/shared
COPY --chown=maisys:maisys services/__init__.py /app/services/__init__.py
COPY --chown=maisys:maisys services/drug-service /app/services/drug-service

# Symlink for hyphen → underscore so Python imports work
RUN ln -s drug-service /app/services/drug_service

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

USER maisys

EXPOSE 8002

# Run migrations then start uvicorn. The alembic upgrade is idempotent.
CMD ["sh", "-c", "cd /app && alembic -c services/drug-service/alembic.ini upgrade head && uvicorn services.drug_service.main:app --host 0.0.0.0 --port 8002"]
