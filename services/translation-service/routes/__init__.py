"""Router registry."""

from fastapi import APIRouter

from services.translation_service.routes.health import router as health_router
from services.translation_service.routes.translation import (
    router as translation_router,
)

ALL_ROUTERS: list[APIRouter] = [health_router, translation_router]

__all__ = ["ALL_ROUTERS"]
