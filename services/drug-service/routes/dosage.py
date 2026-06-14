"""POST /drugs/dosage — invokes the Dosage agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.agents import AgentContext, default_registry
from services.drug_service.agents.dosage import DosageAgent
from services.drug_service.models.schemas import (
    AgentMeta,
    DosageRequest,
    DosageResponse,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/drugs", tags=["dosage"])


@router.post("/dosage", response_model=APIResponse[DosageResponse])
async def dosage(
    request: DosageRequest,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[DosageResponse]:
    if "dosage" not in default_registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AGENT_NOT_REGISTERED", "message": "Dosage agent is not registered."},
        )
    agent: DosageAgent = default_registry.get("dosage")  # type: ignore[assignment]
    context = AgentContext(user_id=user.sub, language=request.language)
    result = await agent.execute(request, context)
    response = DosageResponse(
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
