"""POST /auth/password/reset/request  +  /auth/password/reset/confirm."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequestRequest,
    PasswordResetRequestResponse,
)
from services.password_reset_service import PasswordResetService
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/password/reset/request",
    response_model=APIResponse[PasswordResetRequestResponse],
)
async def request_endpoint(
    body: PasswordResetRequestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PasswordResetRequestResponse]:
    service = PasswordResetService(db)
    await service.request_reset(
        email=body.email,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    # Always-same response — no email enumeration
    return APIResponse[PasswordResetRequestResponse].ok(PasswordResetRequestResponse())


@router.post(
    "/auth/password/reset/confirm",
    response_model=APIResponse[PasswordResetConfirmResponse],
)
async def confirm_endpoint(
    body: PasswordResetConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PasswordResetConfirmResponse]:
    service = PasswordResetService(db)
    await service.confirm_reset(
        token=body.token,
        new_password=body.new_password,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse[PasswordResetConfirmResponse].ok(PasswordResetConfirmResponse())
