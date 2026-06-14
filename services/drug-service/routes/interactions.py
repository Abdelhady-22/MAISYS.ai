"""POST /drugs/interactions — invokes the Interaction agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.agents import AgentContext, default_registry
from services.drug_service.agents.interaction import InteractionAgent
from services.drug_service.models.schemas import (
    AgentMeta,
    InteractionsRequest,
    InteractionsResponse,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/drugs", tags=["interactions"])


@router.post("/interactions", response_model=APIResponse[InteractionsResponse])
async def interactions(
    request: InteractionsRequest,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[InteractionsResponse]:
    if "interaction" not in default_registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AGENT_NOT_REGISTERED",
                "message": "Interaction agent is not registered.",
            },
        )
    agent: InteractionAgent = default_registry.get("interaction")  # type: ignore[assignment]
    context = AgentContext(user_id=user.sub, language=request.language)
    result = await agent.execute(request, context)
    response = InteractionsResponse(
        data=result.data,
        citations=result.citations,
        meta=AgentMeta(
            agent_name=result.meta.agent_name,
            confidence=result.meta.confidence,
            latency_ms=result.meta.latency_ms,
            tokens_used=result.meta.tokens_used,
            disclaimer=result.meta.disclaimer,
        ),
    )
    return APIResponse.ok(response)
