"""Router registry — imported by ``main.py`` and mounted in order."""

from fastapi import APIRouter

from services.safety_service.routes.health import router as health_router
from services.safety_service.routes.safety import router as safety_router

ALL_ROUTERS: list[APIRouter] = [health_router, safety_router]

__all__ = ["ALL_ROUTERS"]
