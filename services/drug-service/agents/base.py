"""BaseAgent abstract class and per-request context.

Every drug-service agent (Lookup, Interaction, Dosage, Comparison,
Pharmacokinetics, Alternative, Web Search, Acquisition) subclasses
``BaseAgent`` and implements ``execute(request, context) -> AgentResponse``.

Public contract:

* ``BaseAgent.name`` is the stable identifier used in routing, logs,
  metrics, and the response envelope's ``agent_name`` field.
* ``BaseAgent.execute()`` is the only entry point. It:
  - Measures latency.
  - Catches all unexpected exceptions, logs them with the
    correlation id, and re-raises as ``AgentExecutionFailure``.
  - Publishes a "started" + "completed"/"failed" progress event when
    the context carries a publisher.
  - Validates the agent's response against the
    ``min_confidence`` floor — below that, raises
    ``AgentLowConfidenceException`` so routes can return a "consult
    a healthcare provider" message instead of a low-quality medical
    answer.

Subclasses implement ``_run(request, context) -> AgentRunResult``;
the public ``execute()`` is final and handles the cross-cutting
concerns above.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel

from services.drug_service.exceptions import (
    AgentExecutionFailure,
    AgentLowConfidenceException,
)
from services.drug_service.models.schemas import (
    AgentMeta,
    BilingualText,
    Citation,
    Language,
)
from shared.error_handler import MaisysException
from shared.logger import get_logger
from shared.progress import ProgressEvent, ProgressPublisher

_log = get_logger(__name__)


RequestT = TypeVar("RequestT", bound=BaseModel)
DataT = TypeVar("DataT", bound=BaseModel)


# ─── Per-request context ──────────────────────────────────────────


@dataclass
class AgentContext:
    """State that lives for one drug-service request.

    Built by the route handler (or by the orchestrator when an agent
    is invoked indirectly) and threaded through every agent call so:

    * Logs from every agent share the same ``correlation_id``.
    * ``language`` is honoured by every bilingual prompt.
    * Progress events from sub-agents flow to the same WebSocket
      channel the original caller subscribed to.
    """

    user_id: str
    language: Language
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    job_id: str | None = None
    """Progress events publish to ``progress:{job_id}``.

    When ``None``, ``execute()`` falls back to ``correlation_id`` for
    the job id — this is the common case for the synchronous REST
    endpoints. The free-text /drugs/query endpoint sets an explicit
    job_id so the WebSocket client can subscribe before the request
    is made.
    """
    progress_publisher: ProgressPublisher | None = None
    extra: dict[str, object] = field(default_factory=dict)
    """Free-form bag for agent-to-agent context (e.g. an upstream
    NormalisedDrug that downstream agents can reuse without re-resolving).
    """

    @property
    def effective_job_id(self) -> str:
        return self.job_id or self.correlation_id


# ─── Agent result and response shapes ─────────────────────────────


@dataclass(frozen=True)
class AgentRunResult(Generic[DataT]):
    """Internal output of ``_run()`` — what the subclass produces.

    The public ``execute()`` wraps this in an ``AgentResponse`` that
    adds latency_ms (measured by the base class) and the disclaimer
    (filled in from the per-agent class attribute when the subclass
    doesn't override).
    """

    data: DataT
    citations: list[Citation]
    confidence: float
    tokens_used: int = 0
    disclaimer: BilingualText | None = None
    """When ``None``, ``execute()`` uses ``BaseAgent.disclaimer``."""


@dataclass(frozen=True)
class AgentResponse(Generic[DataT]):
    """What ``execute()`` returns to the caller (route or orchestrator)."""

    data: DataT
    citations: list[Citation]
    meta: AgentMeta


# ─── Default disclaimers ──────────────────────────────────────────


GENERIC_DISCLAIMER = BilingualText(
    en=(
        "This information is for educational purposes only and is not a "
        "substitute for professional medical advice. Always consult a "
        "qualified healthcare provider before making decisions about "
        "medications."
    ),
    ar=(
        "هذه المعلومات لأغراض تعليمية فقط وليست بديلاً عن المشورة الطبية "
        "المتخصصة. استشر دائماً مقدم رعاية صحية مؤهلاً قبل اتخاذ أي قرار "
        "بشأن الأدوية."
    ),
)


DOSAGE_DISCLAIMER = BilingualText(
    en=(
        "Dosage information provided here is general guidance based on "
        "published sources. Individual dosing must be determined by a "
        "qualified prescriber based on the specific patient. Do not "
        "self-adjust prescribed medication doses."
    ),
    ar=(
        "معلومات الجرعات المقدمة هنا هي إرشادات عامة مبنية على مصادر "
        "منشورة. يجب أن يحدد الجرعة الفردية الطبيب المعالج المؤهل بناءً "
        "على حالة المريض. لا تغير جرعات الأدوية الموصوفة بنفسك."
    ),
)


INTERACTION_DISCLAIMER = BilingualText(
    en=(
        "Drug interaction information here may not cover every case. "
        "Always inform your healthcare provider and pharmacist of every "
        "medication, supplement, and herbal product you take, including "
        "over-the-counter items."
    ),
    ar=(
        "معلومات التفاعلات الدوائية هنا قد لا تغطي جميع الحالات. أبلغ "
        "دائماً مقدم الرعاية الصحية والصيدلي بجميع الأدوية والمكملات "
        "والمنتجات العشبية التي تتناولها، بما في ذلك المستحضرات التي "
        "تصرف بدون وصفة."
    ),
)


# ─── BaseAgent ABC ────────────────────────────────────────────────


class BaseAgent(ABC, Generic[RequestT, DataT]):
    """Abstract base for every drug-service agent.

    Subclass contract:

    * Set ``name`` (class attribute) — stable identifier, lowercase
      underscored.
    * Optionally override ``min_confidence`` (default 0.7) and
      ``disclaimer``.
    * Implement ``async def _run(request, context) -> AgentRunResult``.

    Do NOT override ``execute()`` — it owns latency timing, error
    catching, progress publishing, and the low-confidence gate.
    """

    name: str = ""
    """Stable identifier — keep in sync with the route handler that
    invokes this agent."""

    min_confidence: float = 0.7
    """Below this, ``execute()`` raises ``AgentLowConfidenceException``
    instead of returning the result."""

    disclaimer: BilingualText = GENERIC_DISCLAIMER
    """Subclasses dealing with dosing / interactions should override
    this with the stricter disclaimer."""

    @abstractmethod
    async def _run(self, request: RequestT, context: AgentContext) -> AgentRunResult[DataT]:
        """Subclass-supplied agent body."""
        raise NotImplementedError

    async def execute(self, request: RequestT, context: AgentContext) -> AgentResponse[DataT]:
        """Run the agent with timing, error catching, and progress events."""
        if not self.name:
            raise AssertionError(f"{type(self).__name__} must set `name` class attribute")

        await self._publish_started(context)
        started_at = time.monotonic()
        try:
            result = await self._run(request, context)
        except AgentLowConfidenceException:
            await self._publish_failed(context, "low_confidence")
            raise
        except MaisysException:
            # Any typed MaisysException (DrugNotFound, RxNormAPI, etc.)
            # passes through — the global FastAPI handler translates
            # them into APIResponse envelopes with the right status code.
            await self._publish_failed(context, "execution_failure")
            raise
        except Exception as exc:
            latency_ms = int((time.monotonic() - started_at) * 1000)
            _log.exception(
                "agent.execute.unexpected_error",
                agent=self.name,
                correlation_id=context.correlation_id,
                latency_ms=latency_ms,
                error_type=type(exc).__name__,
            )
            await self._publish_failed(context, "execution_failure")
            raise AgentExecutionFailure(f"{self.name} agent failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started_at) * 1000)

        if result.confidence < self.min_confidence:
            _log.warning(
                "agent.execute.low_confidence",
                agent=self.name,
                correlation_id=context.correlation_id,
                confidence=result.confidence,
                threshold=self.min_confidence,
            )
            await self._publish_failed(context, "low_confidence")
            raise AgentLowConfidenceException(
                f"{self.name} returned confidence {result.confidence:.2f} "
                f"below threshold {self.min_confidence:.2f}"
            )

        meta = AgentMeta(
            agent_name=self.name,
            confidence=result.confidence,
            latency_ms=latency_ms,
            tokens_used=result.tokens_used,
            disclaimer=result.disclaimer or self.disclaimer,
        )
        _log.info(
            "agent.execute.completed",
            agent=self.name,
            correlation_id=context.correlation_id,
            latency_ms=latency_ms,
            confidence=result.confidence,
            tokens_used=result.tokens_used,
        )
        await self._publish_completed(context, latency_ms)
        return AgentResponse(data=result.data, citations=result.citations, meta=meta)

    # ─── Progress helpers ─────────────────────────────────────────

    async def _publish_started(self, context: AgentContext) -> None:
        if context.progress_publisher is None:
            return
        await context.progress_publisher.publish(
            ProgressEvent(
                job_id=context.effective_job_id,
                status="in_progress",
                message=f"{self.name} agent started",
                details={"agent": self.name, "correlation_id": context.correlation_id},
            )
        )

    async def _publish_completed(self, context: AgentContext, latency_ms: int) -> None:
        if context.progress_publisher is None:
            return
        await context.progress_publisher.publish(
            ProgressEvent(
                job_id=context.effective_job_id,
                status="in_progress",
                message=f"{self.name} agent completed",
                details={
                    "agent": self.name,
                    "correlation_id": context.correlation_id,
                    "latency_ms": latency_ms,
                },
            )
        )

    async def _publish_failed(self, context: AgentContext, reason: str) -> None:
        if context.progress_publisher is None:
            return
        await context.progress_publisher.publish(
            ProgressEvent(
                job_id=context.effective_job_id,
                status="failed",
                message=f"{self.name} agent failed",
                details={
                    "agent": self.name,
                    "correlation_id": context.correlation_id,
                    "reason": reason,
                },
            )
        )


# ─── Registry (populated by each agent commit) ────────────────────


class AgentRegistry:
    """Maps agent name → instance.

    Agents register themselves at module import via
    ``AgentRegistry.register(name, factory)``. Commit 12 (orchestrator)
    iterates the registry to discover available agents.
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent[BaseModel, BaseModel]] = {}

    def register(self, agent: BaseAgent[BaseModel, BaseModel]) -> None:
        if not agent.name:
            raise ValueError(f"{type(agent).__name__}.name must be set before registration")
        if agent.name in self._agents:
            raise ValueError(f"Agent {agent.name!r} already registered")
        self._agents[agent.name] = agent
        _log.info("agent.registry.registered", agent=agent.name)

    def get(self, name: str) -> BaseAgent[BaseModel, BaseModel]:
        return self._agents[name]

    def names(self) -> list[str]:
        return sorted(self._agents.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._agents


# Process-wide default registry. Agents in commits 4-11 register
# themselves here at import time.
default_registry = AgentRegistry()


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
