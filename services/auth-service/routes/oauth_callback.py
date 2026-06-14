"""POST /auth/oauth/{provider}/callback."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    OAuthProvider,
    UserPublic,
)
from services.oauth_service import OAuthService
from shared.auth import Role
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/oauth/{provider}/callback",
    response_model=APIResponse[OAuthCallbackResponse],
)
async def oauth_callback_endpoint(
    body: OAuthCallbackRequest,
    request: Request,
    provider: OAuthProvider = Path(..., description="OAuth provider name"),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[OAuthCallbackResponse]:
    service = OAuthService(db)
    result = await service.handle_callback(
        provider=provider,
        id_token=body.id_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        device_info=body.device_info,
    )
    return APIResponse[OAuthCallbackResponse].ok(
        OAuthCallbackResponse(
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
            created=result.created,
        )
    )
