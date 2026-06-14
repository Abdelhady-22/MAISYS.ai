"""POST /drugs/compare — invokes the ComparisonAgent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.agents.comparison import ComparisonAgent
from services.drug_service.agents import AgentContext, default_registry
from services.drug_service.models.schemas import (
    AgentMeta,
    ComparisonRequest,
    ComparisonResponse,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/drugs", tags=["compare"])


@router.post("/compare", response_model=APIResponse[ComparisonResponse])
async def compare(
    request: ComparisonRequest,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[ComparisonResponse]:
    if "comparison" not in default_registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AGENT_NOT_REGISTERED",
                "message": "ComparisonAgent is not registered.",
            },
        )
    agent: ComparisonAgent = default_registry.get("comparison")  # type: ignore[assignment]
    context = AgentContext(user_id=user.sub, language=request.language)
    result = await agent.execute(request, context)
    response = ComparisonResponse(
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
