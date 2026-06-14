"""POST /drugs/lookup — invokes the Lookup agent.

The agent is resolved at request time from
``services.drug_service.agents.default_registry`` so wiring at
service startup (commit 12) only needs to instantiate and register
the agent once.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.drug_service.agents import (
    AgentContext,
    LookupAgent,
    default_registry,
)
from services.drug_service.exceptions import (
    AgentExecutionFailure,
    AgentLowConfidenceException,
    DrugNotFoundException,
)
from services.drug_service.models.schemas import (
    AgentMeta,
    LookupRequest,
    LookupResponse,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/drugs", tags=["lookup"])


@router.post("/lookup", response_model=APIResponse[LookupResponse])
async def lookup(
    request: LookupRequest,
    user: TokenPayload = Depends(get_current_user),
) -> APIResponse[LookupResponse]:
    """Resolve a drug identifier to bilingual structured drug information.

    Returns a single ``LookupResponse`` wrapped in the standard
    ``APIResponse`` envelope. The response includes citations and
    per-agent metadata (latency, confidence, tokens, disclaimer).
    """
    if "lookup" not in default_registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AGENT_NOT_REGISTERED",
                "message": "Lookup agent is not registered with this service.",
            },
        )
    agent: LookupAgent = default_registry.get("lookup")  # type: ignore[assignment]
    context = AgentContext(user_id=user.sub, language=request.language)
    try:
        result = await agent.execute(request, context)
    except DrugNotFoundException:
        raise
    except AgentLowConfidenceException:
        raise
    except AgentExecutionFailure:
        raise

    response = LookupResponse(
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
