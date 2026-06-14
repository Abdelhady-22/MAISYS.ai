"""GET  /auth/me  —  PATCH /auth/me."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import MeResponse, UpdateProfileRequest, UpdateProfileResponse
from services.profile_service import ProfileService, ProfileSnapshot
from shared.auth import Role, TokenPayload, get_current_user
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


def _to_me_response(snapshot: ProfileSnapshot) -> MeResponse:
    user = snapshot.user
    return MeResponse(
        id=user.id,
        email=user.email,
        role=Role(user.role),
        email_verified=user.email_verified,
        is_active=user.is_active,
        language_preference=user.language_preference,
        display_name=snapshot.display_name,
        avatar_url=snapshot.avatar_url,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("/auth/me", response_model=APIResponse[MeResponse])
async def get_me_endpoint(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[MeResponse]:
    service = ProfileService(db)
    snapshot = await service.get_me(UUID(current_user.sub))
    return APIResponse[MeResponse].ok(_to_me_response(snapshot))


@router.patch("/auth/me", response_model=APIResponse[UpdateProfileResponse])
async def patch_me_endpoint(
    body: UpdateProfileRequest,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[UpdateProfileResponse]:
    service = ProfileService(db)
    result = await service.update_profile(
        user_id=UUID(current_user.sub),
        email=body.email,
        display_name=body.display_name,
        avatar_url=body.avatar_url,
        language_preference=body.language_preference,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse[UpdateProfileResponse].ok(
        UpdateProfileResponse(
            user=_to_me_response(result.snapshot),
            email_reverification_required=result.email_reverification_required,
            message=result.message,
        )
    )
