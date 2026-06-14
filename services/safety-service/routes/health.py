"""Health, readiness, and metrics endpoints.

* ``/healthz`` — liveness probe; always 200 once the process is up.
  Kubernetes uses this to decide whether to restart the pod.
* ``/readyz`` — readiness probe; returns 200 only when the service
  is wired up enough to serve traffic. For safety-service this is
  trivially "process started" because the detector is in-memory.
* ``/metrics`` — Prometheus text-format. The actual metrics are
  collected by ``prometheus-fastapi-instrumentator`` mounted in
  ``main.py``; this endpoint is just the scrape target.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness")
async def readyz() -> dict[str, str]:
    # Stateless service — detectors are in-memory, no external
    # dependency to probe. If Stage 2 LLM is enabled, a future
    # enhancement could ping the model-router or LiteLLM healthcheck,
    # but Stage 2 is best-effort so we don't gate readiness on it.
    return {"status": "ready"}
