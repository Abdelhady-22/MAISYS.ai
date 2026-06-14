"""Agent framework — BaseAgent ABC, per-request context, and registry.

The 8 concrete agents (Lookup, Interaction, Dosage, Comparison,
Pharmacokinetics, Alternative, Web Search, Acquisition) are added in
commits 4-11 and register themselves with ``default_registry``.
"""

from services.drug_service.agents.base import (
    DOSAGE_DISCLAIMER,
    GENERIC_DISCLAIMER,
    INTERACTION_DISCLAIMER,
    AgentContext,
    AgentRegistry,
    AgentResponse,
    AgentRunResult,
    BaseAgent,
    default_registry,
)

__all__ = [
    "AgentContext",
    "AgentRegistry",
    "AgentResponse",
    "AgentRunResult",
    "BaseAgent",
    "DOSAGE_DISCLAIMER",
    "GENERIC_DISCLAIMER",
    "INTERACTION_DISCLAIMER",
    "default_registry",
]
