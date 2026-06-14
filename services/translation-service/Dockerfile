# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS build

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY shared /build/shared
COPY services/translation-service/requirements.txt /build/translation-requirements.txt

RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r /build/shared/requirements.txt \
    && pip install --no-cache-dir -r /build/translation-requirements.txt

FROM python:3.12-slim AS runtime

RUN groupadd --system maisys && useradd --system --gid maisys --uid 1000 maisys

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

WORKDIR /app

COPY --chown=maisys:maisys shared /app/shared
COPY --chown=maisys:maisys services/__init__.py /app/services/__init__.py
COPY --chown=maisys:maisys services/translation-service /app/services/translation-service

RUN ln -s translation-service /app/services/translation_service

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

USER maisys

EXPOSE 8007

# Stateless service — no Alembic step
CMD ["uvicorn", "services.translation_service.main:app", "--host", "0.0.0.0", "--port", "8007"]
