"""Acquisition endpoint stub.

Stub returning 501. The actual agent lands in commit 11.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import AcquisitionRequest, AcquisitionResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["acquisition"])


@router.post("/acquisition", response_model=AcquisitionResponse)
async def acquisition(
    request: AcquisitionRequest,
    user: TokenPayload = Depends(get_current_user),
) -> AcquisitionResponse:
    """Availability and price tier by country.

    Not yet implemented — agent commit 11 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "acquisition agent not yet implemented",
        },
    )
