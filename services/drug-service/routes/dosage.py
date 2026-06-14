"""Dosage endpoint stub.

Stub returning 501. The actual agent lands in commit 6.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import DosageRequest, DosageResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["dosage"])


@router.post("/dosage", response_model=DosageResponse)
async def dosage(
    request: DosageRequest,
    user: TokenPayload = Depends(get_current_user),
) -> DosageResponse:
    """Dosage with patient context (age, weight, renal/hepatic).

    Not yet implemented — agent commit 6 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "dosage agent not yet implemented",
        },
    )
