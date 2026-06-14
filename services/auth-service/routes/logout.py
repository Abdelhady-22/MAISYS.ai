"""POST /auth/logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import LogoutResponse
from services.token_service import TokenService
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.post("/auth/logout", response_model=APIResponse[LogoutResponse])
async def logout_endpoint(
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[LogoutResponse]:
    service = TokenService(db)
    await service.logout(
        jwt_jti=current_user.jti,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse[LogoutResponse].ok(LogoutResponse(message="Logged out"))
