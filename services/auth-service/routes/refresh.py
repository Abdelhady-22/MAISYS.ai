"""POST /auth/refresh."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import RefreshRequest, RefreshResponse
from services.token_service import TokenService
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.post("/auth/refresh", response_model=APIResponse[RefreshResponse])
async def refresh_endpoint(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[RefreshResponse]:
    service = TokenService(db)
    new_tokens = await service.refresh(
        refresh_token=body.refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse[RefreshResponse].ok(
        RefreshResponse(
            access_token=new_tokens.access_token,
            refresh_token=new_tokens.refresh_token,
            expires_in=new_tokens.expires_in,
        )
    )
