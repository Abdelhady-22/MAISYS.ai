"""drug-service exception hierarchy.

All exceptions inherit from ``shared.error_handler.MaisysException``
so the global FastAPI handler translates them to the standard
``APIResponse`` envelope automatically.

Use these instead of raising bare ``HTTPException`` from routes or
services — the structured ``code`` field is what the frontend keys on.
"""

from __future__ import annotations

from shared.error_handler import (
    ConflictException,
    ExternalServiceException,
    MaisysException,
    MedicalSafetyException,
    NotFoundException,
    ValidationException,
)

# ─── Normalisation ────────────────────────────────────────────────


class DrugNotFoundException(NotFoundException):
    """No RxCUI could be resolved for the input drug name."""

    code = "DRUG_NOT_FOUND"


class UnknownDrugIdentifierException(ValidationException):
    """The caller submitted a DrugIdentifier with neither name nor rxcui."""

    code = "UNKNOWN_DRUG_IDENTIFIER"


class AmbiguousDrugException(ConflictException):
    """The input matched multiple distinct drugs with similar confidence."""

    code = "AMBIGUOUS_DRUG"


# ─── Agents / orchestrator ────────────────────────────────────────


class AgentExecutionFailure(MaisysException):
    """An agent crashed or timed out while building its response."""

    code = "AGENT_EXECUTION_FAILURE"
    status_code = 502


class AgentLowConfidenceException(MaisysException):
    """The agent returned a response below the per-agent confidence floor.

    Routes typically convert this into a 422 with a "consult a
    healthcare provider" prompt rather than returning a low-quality
    medical answer.
    """

    code = "AGENT_LOW_CONFIDENCE"
    status_code = 422


class OrchestratorRoutingFailure(MaisysException):
    """The LangGraph router could not select an agent for the query."""

    code = "ORCHESTRATOR_ROUTING_FAILURE"
    status_code = 422


# ─── External dependencies ────────────────────────────────────────


class RxNormAPIException(ExternalServiceException):
    """The RxNorm API returned an error or was unreachable."""

    code = "RXNORM_API_FAILURE"


class WebSearchException(ExternalServiceException):
    """The drugs.com / DailyMed web-search agent failed (network, rate-limit, blocked)."""

    code = "WEB_SEARCH_FAILURE"


class DrugRAGException(ExternalServiceException):
    """A query to the drugs_en / drugs_ar Qdrant collections failed."""

    code = "DRUG_RAG_FAILURE"


# ─── Safety ───────────────────────────────────────────────────────


class SelfHarmDetectedException(MedicalSafetyException):
    """The safety-service flagged the input as potential self-harm or overdose intent."""

    code = "SELF_HARM_DETECTED"


__all__ = [
    "AgentExecutionFailure",
    "AgentLowConfidenceException",
    "AmbiguousDrugException",
    "DrugNotFoundException",
    "DrugRAGException",
    "OrchestratorRoutingFailure",
    "RxNormAPIException",
    "SelfHarmDetectedException",
    "UnknownDrugIdentifierException",
    "WebSearchException",
]
