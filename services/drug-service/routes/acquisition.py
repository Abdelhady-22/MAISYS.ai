"""POST /drugs/acquisition — invokes the AcquisitionAgent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.agents.single_drug_agents import AcquisitionAgent
from services.drug_service.agents import AgentContext, default_registry
from services.drug_service.models.schemas import (
    AgentMeta,
    AcquisitionRequest,
    AcquisitionResponse,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/drugs", tags=["acquisition"])


@router.post("/acquisition", response_model=APIResponse[AcquisitionResponse])
async def acquisition(
    request: AcquisitionRequest,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[AcquisitionResponse]:
    if "acquisition" not in default_registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AGENT_NOT_REGISTERED",
                "message": "AcquisitionAgent is not registered.",
            },
        )
    agent: AcquisitionAgent = default_registry.get("acquisition")  # type: ignore[assignment]
    context = AgentContext(user_id=user.sub, language=request.language)
    result = await agent.execute(request, context)
    response = AcquisitionResponse(
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
