"""Health, readiness, metrics."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness — modes wired")
async def readyz(request: Request) -> dict[str, object]:
    selector = getattr(request.app.state, "mode_selector", None)
    if selector is None:
        return {"status": "unwired"}
    modes = selector.available_modes()
    if not modes:
        return {"status": "no_modes_available"}
    return {"status": "ready", "modes": modes}
