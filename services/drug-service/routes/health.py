"""Health and readiness endpoints.

``/healthz`` is shallow — process is alive. ``/readyz`` is deep —
the database and Redis connections work. K8s and docker-compose
healthchecks should point at ``/readyz`` for the load-balancer
gating; ``/healthz`` is for the liveness probe.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.error_handler import APIResponse
from shared.logger import get_logger
from shared.models import get_db_session

_log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=APIResponse[dict[str, str]])
async def healthz() -> APIResponse[dict[str, str]]:
    """Liveness — process is up and responding to HTTP."""
    return APIResponse.ok({"status": "ok"})


@router.get("/readyz", response_model=APIResponse[dict[str, Any]])
async def readyz(
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, Any]]:
    """Readiness — service can talk to its dependencies.

    Checks:
    * Postgres ``SELECT 1`` round-trips successfully.

    Redis check is added when the LLM cache is wired (commit 12).
    Qdrant check is added when the RAG agents come online.
    """
    checks: dict[str, str] = {"postgres": "unknown"}
    try:
        await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        _log.warning("readyz.postgres_unavailable", error=str(e))
        checks["postgres"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    return APIResponse.ok({"status": "ok" if all_ok else "degraded", "checks": checks})
