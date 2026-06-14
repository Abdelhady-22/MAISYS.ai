"""Alternatives endpoint stub.

Stub returning 501. The actual agent lands in commit 9.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import AlternativeRequest, AlternativeResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["alternatives"])


@router.post("/alternatives", response_model=AlternativeResponse)
async def alternatives(
    request: AlternativeRequest,
    user: TokenPayload = Depends(get_current_user),
) -> AlternativeResponse:
    """Alternatives given a drug and a reason to switch.

    Not yet implemented — agent commit 9 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "alternatives agent not yet implemented",
        },
    )
