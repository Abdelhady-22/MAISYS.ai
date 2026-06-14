"""Interactions endpoint stub.

Stub returning 501. The actual agent lands in commit 5.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import InteractionsRequest, InteractionsResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["interactions"])


@router.post("/interactions", response_model=InteractionsResponse)
async def interactions(
    request: InteractionsRequest,
    user: TokenPayload = Depends(get_current_user),
) -> InteractionsResponse:
    """Tiered interaction check: DDIMDL → drug_rag → web search.

    Not yet implemented — agent commit 5 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "interactions agent not yet implemented",
        },
    )
