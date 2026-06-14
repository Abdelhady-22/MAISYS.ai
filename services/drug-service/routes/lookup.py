"""Lookup endpoint stub.

Stub returning 501. The actual agent lands in commit 4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import LookupRequest, LookupResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["lookup"])


@router.post("/lookup", response_model=LookupResponse)
async def lookup(
    request: LookupRequest,
    user: TokenPayload = Depends(get_current_user),
) -> LookupResponse:
    """Drug lookup — RxNorm + drug_rag → generic/brand/CUI/class/indications.

    Not yet implemented — agent commit 4 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "lookup agent not yet implemented",
        },
    )
