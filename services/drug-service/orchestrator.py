"""LangGraph orchestrator for free-text drug queries.

Routes ``POST /drugs/query`` to the right agent(s) based on
intent classification. Streams progress events via
``ProgressPublisher`` so a WebSocket client (PR3) can subscribe.

State graph:

    START
      ↓
    classify_intent   (LLM call: intent ∈ {lookup, interaction,
                       dosage, comparison, pharmacokinetics,
                       alternative, acquisition, unknown})
      ↓
    safety_check      (call safety-service; raise on flagged)
      ↓
    dispatch_agent    (invoke the chosen agent's execute())
      ↓
    END

When the user's free-text doesn't map cleanly to one agent (e.g. "tell
me about ibuprofen and warfarin together — is it safe and what dose?"),
the classifier picks the most specific applicable agent — interaction
in that example — and the route returns its result. Multi-agent fan-out
is left to PR3 where the visual auto-trigger can render multiple cards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.drug_service.agents._llm_helpers import (
    synthesise_json,
)
from services.drug_service.agents.base import (
    AgentContext,
    AgentRegistry,
    AgentResponse,
    GENERIC_DISCLAIMER,
)
from services.drug_service.exceptions import OrchestratorRoutingFailure
from services.drug_service.models.schemas import (
    AcquisitionRequest,
    AgentMeta,
    AlternativeRequest,
    ComparisonRequest,
    DosageRequest,
    DrugIdentifier,
    InteractionsRequest,
    Language,
    LookupRequest,
    PatientContext,
    PKRequest,
    QueryRequest,
    QueryResponse,
    VisualType,
)
from services.drug_service.utils.safety import check_query_safety
from shared.llm_client import LLMClient
from shared.logger import get_logger
from shared.progress import ProgressEvent, ProgressPublisher

_log = get_logger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"
PROMPTS_DIR = Path(__file__).parent / "agents" / "prompts"


# ─── Intent classifier output ─────────────────────────────────────


class _IntentClassification(BaseModel):
    intent: str = "unknown"
    """One of: lookup, interaction, dosage, comparison, pharmacokinetics,
    alternative, acquisition, unknown."""
    drug_names: list[str] = Field(default_factory=list)
    """Drug names extracted from the free-text query, in input order."""
    reason: str = ""
    """For 'alternative' intent: the reason to switch (e.g. 'cough')."""
    country_iso: str | None = None
    """For 'acquisition' intent: ISO 3166-1 alpha-2 country code."""
    patient_age_years: int | None = None
    """For 'dosage' intent: age extracted from the query, if any."""


VALID_INTENTS = {
    "lookup",
    "interaction",
    "dosage",
    "comparison",
    "pharmacokinetics",
    "alternative",
    "acquisition",
}


_INTENT_TO_VISUAL: dict[str, VisualType] = {
    "lookup": "card",
    "interaction": "severity_bar",
    "dosage": "dosing_flowchart",
    "comparison": "comparison_table",
    "pharmacokinetics": "pk_curve",
    "alternative": "card",
    "acquisition": "card",
}


# ─── Orchestrator ─────────────────────────────────────────────────


class DrugQueryOrchestrator:
    """Routes free-text /drugs/query to the right registered agent."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        llm_client: LLMClient,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._registry = registry
        self._llm = llm_client
        self._model = model

    async def run(
        self,
        request: QueryRequest,
        *,
        user_id: str,
        progress_publisher: ProgressPublisher | None = None,
        job_id: str | None = None,
    ) -> QueryResponse:
        # PR3: prefer explicit job_id kwarg, fall back to request.job_id.
        # Allows server-driven job ids when the client doesn't supply one
        # while still letting the client bind the channel for WebSocket use.
        effective_job_id = job_id or request.job_id
        context = AgentContext(
            user_id=user_id,
            language=request.language,
            progress_publisher=progress_publisher,
            job_id=effective_job_id,
        )

        # Step 1: safety check (best-effort, swallows 404)
        await self._publish(context, "in_progress", "Running safety check…")
        await check_query_safety(
            request.text,
            user_id=user_id,
            correlation_id=context.correlation_id,
        )

        # Step 2: intent classification
        await self._publish(context, "in_progress", "Classifying intent…")
        classification = await self._classify(request)
        _log.info(
            "orchestrator.classified",
            correlation_id=context.correlation_id,
            intent=classification.intent,
            n_drugs=len(classification.drug_names),
        )

        if classification.intent == "unknown" or classification.intent not in VALID_INTENTS:
            raise OrchestratorRoutingFailure(
                f"Cannot route query — intent '{classification.intent}' is not a known agent"
            )

        if not classification.drug_names:
            raise OrchestratorRoutingFailure(
                "Cannot route query — no drug names detected in the query"
            )

        # Step 3: dispatch to the agent
        await self._publish(
            context,
            "in_progress",
            f"Dispatching to {classification.intent} agent…",
        )
        agent_response, data_dict = await self._dispatch(classification, context)

        await self._publish(context, "completed", "Query completed")

        return QueryResponse(
            primary_agent=classification.intent,
            called_agents=[classification.intent],
            data=data_dict,
            citations=agent_response.citations,
            meta=agent_response.meta,
            visual_type=_INTENT_TO_VISUAL.get(classification.intent, "card"),
        )

    # ─── Step helpers ─────────────────────────────────────────────

    async def _classify(self, request: QueryRequest) -> _IntentClassification:
        system = "You classify drug-information queries. Output JSON only."
        user_prompt = self._classifier_user_prompt(request.text, request.language)
        # We don't strictly need shared synthesise_json's retry-on-parse
        # here, but reusing it gives us free hardening.
        try:
            classification, _tokens = await synthesise_json(
                llm_client=self._llm,
                model=self._model,
                system_prompt=system,
                user_prompt=user_prompt,
                schema=_IntentClassification,
                max_tokens=400,
                temperature=0.0,
            )
        except Exception as exc:
            raise OrchestratorRoutingFailure(f"Intent classification failed: {exc}") from exc
        return classification

    def _classifier_user_prompt(self, text: str, language: Language) -> str:
        intents_list = ", ".join(sorted(VALID_INTENTS)) + ", unknown"
        return (
            f"User query (language={language}):\n"
            f'"""\n{text}\n"""\n\n'
            "Classify the query into one of these intents:\n"
            f"  {intents_list}\n\n"
            "Intent definitions:\n"
            "- lookup: general info about a single drug (mechanism, indications, brand names)\n"
            "- interaction: how two or more drugs interact\n"
            "- dosage: how much / how often to take a drug\n"
            "- comparison: side-by-side compare of two or more drugs\n"
            "- pharmacokinetics: absorption, distribution, metabolism, excretion details\n"
            "- alternative: alternatives to a drug given a reason (side effect, allergy)\n"
            "- acquisition: where to buy / availability / price in a country\n"
            "- unknown: cannot determine\n\n"
            "Output JSON:\n"
            "{\n"
            '  "intent": "lookup" | "interaction" | "dosage" | "comparison" | '
            '"pharmacokinetics" | "alternative" | "acquisition" | "unknown",\n'
            '  "drug_names": ["drug1", "drug2", ...],\n'
            '  "reason": "...",         // only for alternative intent\n'
            '  "country_iso": "EG",      // only for acquisition intent (ISO 3166-1 alpha-2)\n'
            '  "patient_age_years": 65   // only for dosage intent, if age is mentioned\n'
            "}\n"
        )

    async def _dispatch(
        self, classification: _IntentClassification, context: AgentContext
    ) -> tuple[AgentResponse[Any], dict[str, Any]]:
        """Build the per-agent request, invoke the agent, return its result + data dict."""
        if classification.intent not in self._registry:
            raise OrchestratorRoutingFailure(
                f"Intent '{classification.intent}' is recognised but no agent is registered for it"
            )

        agent = self._registry.get(classification.intent)
        names = classification.drug_names
        language = context.language
        req: Any  # union of per-agent request shapes

        if classification.intent == "lookup":
            req = LookupRequest(drug=DrugIdentifier(name=names[0]), language=language)
        elif classification.intent == "interaction":
            if len(names) < 2:
                raise OrchestratorRoutingFailure(
                    "interaction intent requires at least 2 drug names"
                )
            req = InteractionsRequest(
                drugs=[DrugIdentifier(name=n) for n in names], language=language
            )
        elif classification.intent == "dosage":
            patient = PatientContext(age_years=classification.patient_age_years)
            req = DosageRequest(
                drug=DrugIdentifier(name=names[0]), patient=patient, language=language
            )
        elif classification.intent == "comparison":
            if len(names) < 2:
                raise OrchestratorRoutingFailure("comparison intent requires at least 2 drug names")
            req = ComparisonRequest(
                drugs=[DrugIdentifier(name=n) for n in names], language=language
            )
        elif classification.intent == "pharmacokinetics":
            req = PKRequest(drug=DrugIdentifier(name=names[0]), language=language)
        elif classification.intent == "alternative":
            req = AlternativeRequest(
                drug=DrugIdentifier(name=names[0]),
                reason=classification.reason or "alternative needed",
                language=language,
            )
        elif classification.intent == "acquisition":
            req = AcquisitionRequest(
                drug=DrugIdentifier(name=names[0]),
                country_iso=(classification.country_iso or "US").upper(),
                language=language,
            )
        else:
            raise OrchestratorRoutingFailure(f"Unsupported intent: {classification.intent}")

        response = await agent.execute(req, context)
        data_dict = response.data.model_dump(mode="json")
        return response, data_dict

    async def _publish(
        self,
        context: AgentContext,
        status: Literal["started", "in_progress", "completed", "failed"],
        message: str,
    ) -> None:
        if context.progress_publisher is None:
            return
        await context.progress_publisher.publish(
            ProgressEvent(
                job_id=context.effective_job_id,
                status=status,
                message=message,
                details={"correlation_id": context.correlation_id},
            )
        )


def _fallback_meta() -> AgentMeta:
    """Used when the orchestrator can't dispatch — generic disclaimer applies."""
    return AgentMeta(
        agent_name="orchestrator",
        confidence=0.0,
        latency_ms=0,
        tokens_used=0,
        disclaimer=GENERIC_DISCLAIMER,
    )


__all__ = ["DrugQueryOrchestrator"]
