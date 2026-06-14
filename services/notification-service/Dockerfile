# syntax=docker/dockerfile:1.7

# ── build stage ───────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY shared /build/shared
COPY services/notification-service/requirements.txt /build/notification-requirements.txt

RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r /build/shared/requirements.txt \
    && pip install --no-cache-dir -r /build/notification-requirements.txt

# ── runtime stage ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN groupadd --system maisys && useradd --system --gid maisys --uid 1000 maisys

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

WORKDIR /app

COPY --chown=maisys:maisys shared /app/shared
COPY --chown=maisys:maisys services/__init__.py /app/services/__init__.py
COPY --chown=maisys:maisys services/notification-service /app/services/notification-service

# Underscore alias so `services.notification_service.*` imports resolve.
RUN ln -s notification-service /app/services/notification_service

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

USER maisys

EXPOSE 8009

# Run Alembic migrations before booting the app — fail fast if the DB
# schema doesn't match. The container exits with an error if migrations
# fail, so Kubernetes/Compose will surface the problem in logs.
CMD ["sh", "-c", "alembic -c services/notification-service/alembic.ini upgrade head && uvicorn services.notification_service.main:app --host 0.0.0.0 --port 8009"]
