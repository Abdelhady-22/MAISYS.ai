"""Pharmacokinetics endpoint stub.

Stub returning 501. The actual agent lands in commit 8.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import PKRequest, PKResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["pharmacokinetics"])


@router.post("/pharmacokinetics", response_model=PKResponse)
async def pharmacokinetics(
    request: PKRequest,
    user: TokenPayload = Depends(get_current_user),
) -> PKResponse:
    """Absorption, distribution, metabolism, excretion.

    Not yet implemented — agent commit 8 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "pharmacokinetics agent not yet implemented",
        },
    )
