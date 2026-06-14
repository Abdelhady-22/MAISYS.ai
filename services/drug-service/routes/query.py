"""Query endpoint stub.

Stub returning 501. The actual agent lands in commit 12.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.models.schemas import QueryRequest, QueryResponse
from shared.auth import TokenPayload, get_current_user

router = APIRouter(prefix="/drugs", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    user: TokenPayload = Depends(get_current_user),
) -> QueryResponse:
    """Free-text query routed through the LangGraph orchestrator.

    Not yet implemented — agent commit 12 supplies the
    behaviour. This route exists so the OpenAPI surface is locked from
    PR2 commit 1.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "query agent not yet implemented",
        },
    )
