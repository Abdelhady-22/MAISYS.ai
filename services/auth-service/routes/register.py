"""POST /auth/register."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import RegisterRequest, RegisterResponse
from services.registration_service import RegistrationService
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register",
    response_model=APIResponse[RegisterResponse],
    status_code=201,
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[RegisterResponse]:
    service = RegistrationService(db)
    user_id = await service.register(
        email=body.email,
        password=body.password,
        language_preference=body.language_preference,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse[RegisterResponse].ok(
        RegisterResponse(
            user_id=user_id,
            email=body.email,
            message="Verification code sent. Please check your email.",
        )
    )
