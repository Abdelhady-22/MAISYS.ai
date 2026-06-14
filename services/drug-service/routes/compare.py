"""Compare endpoint stub.

Stub returning 501. The actual agent lands in commit 7.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import ComparisonRequest, ComparisonResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["compare"])


@router.post("/compare", response_model=ComparisonResponse)
async def compare(
    request: ComparisonRequest,
    user: TokenPayload = Depends(get_current_user),
) -> ComparisonResponse:
    """Side-by-side drug comparison.

    Not yet implemented — agent commit 7 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "compare agent not yet implemented",
        },
    )
