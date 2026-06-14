"""Router registry."""

from fastapi import APIRouter

from services.notification_service.routes.health import router as health_router
from services.notification_service.routes.notifications import (
    router as notifications_router,
)

ALL_ROUTERS: list[APIRouter] = [health_router, notifications_router]

__all__ = ["ALL_ROUTERS"]
