"""POST /auth/login."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    LoginRequest,
    LoginResponse,
    OTPRequiredResponse,
    UserPublic,
)
from services.login_service import LoginOTPRequired, LoginService, LoginTokens
from shared.auth import Role
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/login",
    response_model=APIResponse[LoginResponse | OTPRequiredResponse],
)
async def login_endpoint(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[Any]:
    service = LoginService(db)
    result = await service.login(
        email=body.email,
        password=body.password,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        device_info=body.device_info,
    )

    if isinstance(result, LoginTokens):
        return APIResponse[LoginResponse].ok(
            LoginResponse(
                access_token=result.access_token,
                refresh_token=result.refresh_token,
                expires_in=result.expires_in,
                user=UserPublic(
                    id=result.user.id,
                    email=result.user.email,
                    role=Role(result.user.role),
                    email_verified=result.user.email_verified,
                    language_preference=result.user.language_preference,
                ),
            )
        )

    # OTP gate
    assert isinstance(result, LoginOTPRequired)
    return APIResponse[OTPRequiredResponse].ok(
        OTPRequiredResponse(
            otp_token=result.user_id,
            message=result.message,
        )
    )
