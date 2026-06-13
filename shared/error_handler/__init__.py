"""MAISYS shared error_handler module.

Provides:
- MaisysException base class and 8 concrete subclasses for typed errors
- APIResponse envelope for consistent API responses across services
- ErrorDetail payload model
- setup_exception_handlers() to wire global FastAPI exception handling

Typical service-side usage:

    from fastapi import FastAPI
    from shared.error_handler import (
        APIResponse, NotFoundException, setup_exception_handlers,
    )

    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/users/{user_id}")
    async def get_user(user_id: str) -> APIResponse[dict]:
        user = await repo.get(user_id)
        if user is None:
            raise NotFoundException(f"User {user_id} not found",
                                    details={"user_id": user_id})
        return APIResponse.ok({"id": user.id, "email": user.email})
"""

from shared.error_handler.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    ExternalServiceException,
    MaisysException,
    MedicalSafetyException,
    NotFoundException,
    RateLimitException,
    ValidationException,
)
from shared.error_handler.handler import setup_exception_handlers
from shared.error_handler.response import APIResponse, ErrorDetail

__all__ = [
    "APIResponse",
    "AuthenticationException",
    "AuthorizationException",
    "ConflictException",
    "ErrorDetail",
    "ExternalServiceException",
    "MaisysException",
    "MedicalSafetyException",
    "NotFoundException",
    "RateLimitException",
    "ValidationException",
    "setup_exception_handlers",
]
