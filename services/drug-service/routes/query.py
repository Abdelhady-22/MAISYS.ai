"""POST /drugs/query — free-text routed through the LangGraph orchestrator."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from services.drug_service.models.schemas import QueryRequest, QueryResponse
from services.drug_service.orchestrator import DrugQueryOrchestrator
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse
from shared.progress import ProgressPublisher

router = APIRouter(prefix="/drugs", tags=["query"])


@router.post("/query", response_model=APIResponse[QueryResponse])
async def query(
    request: QueryRequest,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[QueryResponse]:
    """Free-text drug query routed through the orchestrator.

    PR3: when ``request.job_id`` is set, progress events are published
    to the ``progress:{job_id}`` Redis channel for WebSocket consumption.
    The publisher is attached to ``app.state.progress_publisher`` at
    startup (wiring.py); when absent, progress events are silently
    dropped and the request still completes normally.
    """
    orchestrator: DrugQueryOrchestrator | None = getattr(
        http_request.app.state, "orchestrator", None
    )
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ORCHESTRATOR_NOT_WIRED",
                "message": "Query orchestrator is not yet wired (waiting on startup).",
            },
        )

    publisher: ProgressPublisher | None = getattr(
        http_request.app.state, "progress_publisher", None
    )
    response = await orchestrator.run(
        request,
        user_id=user.sub,
        progress_publisher=publisher,
    )
    return APIResponse.ok(response)
