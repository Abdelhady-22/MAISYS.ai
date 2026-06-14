"""GET /auth/sessions  —  DELETE /auth/sessions/{id}."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    DeleteSessionResponse,
    SessionInfo,
    SessionListResponse,
)
from services.profile_service import ProfileService
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse
from shared.models import get_db_session

router = APIRouter(tags=["auth"])


@router.get("/auth/sessions", response_model=APIResponse[SessionListResponse])
async def list_sessions_endpoint(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SessionListResponse]:
    service = ProfileService(db)
    rows = await service.list_sessions(UUID(current_user.sub))
    return APIResponse[SessionListResponse].ok(
        SessionListResponse(
            sessions=[
                SessionInfo(
                    id=s.id,
                    issued_at=s.issued_at,
                    expires_at=s.expires_at,
                    user_agent=s.user_agent,
                    ip_address=s.ip_address,
                    revoked=s.revoked,
                )
                for s in rows
            ]
        )
    )


@router.delete(
    "/auth/sessions/{session_id}",
    response_model=APIResponse[DeleteSessionResponse],
)
async def delete_session_endpoint(
    request: Request,
    session_id: UUID = Path(...),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[DeleteSessionResponse]:
    service = ProfileService(db)
    await service.revoke_session(
        user_id=UUID(current_user.sub),
        session_id=session_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse[DeleteSessionResponse].ok(DeleteSessionResponse(message="Session revoked"))
