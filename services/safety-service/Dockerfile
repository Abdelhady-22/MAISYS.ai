# syntax=docker/dockerfile:1.7

# ── build stage ───────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY shared /build/shared
COPY services/safety-service/requirements.txt /build/safety-requirements.txt

RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r /build/shared/requirements.txt \
    && pip install --no-cache-dir -r /build/safety-requirements.txt

# ── runtime stage ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN groupadd --system maisys && useradd --system --gid maisys --uid 1000 maisys

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

WORKDIR /app

COPY --chown=maisys:maisys shared /app/shared
COPY --chown=maisys:maisys services/__init__.py /app/services/__init__.py
COPY --chown=maisys:maisys services/safety-service /app/services/safety-service

# Underscore alias so `services.safety_service.*` imports resolve.
RUN ln -s safety-service /app/services/safety_service

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

USER maisys

EXPOSE 8008

# Safety-service is stateless — no Alembic migration step.
CMD ["uvicorn", "services.safety_service.main:app", "--host", "0.0.0.0", "--port", "8008"]
