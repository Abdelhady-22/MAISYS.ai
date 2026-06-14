"""POST /drugs/pharmacokinetics — invokes the PharmacokineticsAgent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.agents.single_drug_agents import PharmacokineticsAgent
from services.drug_service.agents import AgentContext, default_registry
from services.drug_service.models.schemas import (
    AgentMeta,
    PKRequest,
    PKResponse,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/drugs", tags=["pharmacokinetics"])


@router.post("/pharmacokinetics", response_model=APIResponse[PKResponse])
async def pharmacokinetics(
    request: PKRequest,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[PKResponse]:
    if "pharmacokinetics" not in default_registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AGENT_NOT_REGISTERED",
                "message": "PharmacokineticsAgent is not registered.",
            },
        )
    agent: PharmacokineticsAgent = default_registry.get("pharmacokinetics")  # type: ignore[assignment]
    context = AgentContext(user_id=user.sub, language=request.language)
    result = await agent.execute(request, context)
    response = PKResponse(
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
