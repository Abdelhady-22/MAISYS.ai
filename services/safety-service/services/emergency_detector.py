"""Emergency detection — Stage 1 regex + Stage 2 LLM confirmation.

Implements the two-stage detection algorithm from Part 5 §5.1.

Stage 1 (always on):
    Run normalised input against the ``ALL_CLEAR_PATTERNS`` list. Any
    match → emergency, return immediately. This is O(N_patterns) per
    request and finishes in well under a millisecond.

Stage 1.5 (always on):
    Run input against ``ALL_AMBIGUOUS_PATTERNS``. A match here flags
    the input as "possibly an emergency, needs Stage 2 confirmation".

Stage 2 (optional, opt-in via ``SAFETY_LLM_CONFIRM_ENABLED``):
    Send the input plus the matched pattern to a small fast LLM
    asking ``"Is this text describing a current medical emergency
    happening to the person right now? Answer only YES or NO."`` with
    temperature 0 and a 5s timeout. YES → emergency, NO or timeout →
    not emergency.

In Phase 3 v1 Stage 2 is shipped wired-up but **disabled by
default**. Enabling it requires
``SAFETY_LLM_CONFIRM_ENABLED=true`` in the environment. The
rationale: we don't yet have a labelled fixture set to tune the
ambiguous-pattern list against, and the LLM call adds 500-2000ms of
p95 latency. Conservatively, ambiguous matches fall through to "not
an emergency" until tuning data is available.

This decision is documented in the conflicts log (P3-C04). The
hook is in place so flipping the flag is the only change required
once tuning is done.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Literal

from services.safety_service.exceptions.exceptions import SafetyLLMTimeout
from services.safety_service.models.patterns import (
    ALL_AMBIGUOUS_PATTERNS,
    ALL_CLEAR_PATTERNS,
    EmergencyPattern,
)
from services.safety_service.models.schemas import (
    EmergencyCategory,
    EmergencyResponse,
)
from services.safety_service.services.arabic_normalizer import (
    normalise_for_matching,
)
from services.safety_service.services.emergency_templates import (
    build_emergency_response,
)
from shared.llm_client import CompletionRequest, LLMClient, Message
from shared.logger import get_logger

_log = get_logger(__name__)

DEFAULT_LLM_TIMEOUT_SECONDS = 5.0
DEFAULT_STAGE_2_MODEL = "openai/gpt-4o-mini"
DEFAULT_STAGE_2_PROMPT_SYSTEM = (
    "You judge whether a short message is describing a CURRENT medical "
    "emergency happening to the person writing it RIGHT NOW. "
    "Reply with exactly one word: YES or NO. Nothing else."
)


@dataclass(frozen=True)
class DetectionResult:
    """What the detector returns to the route layer.

    The route then composes the public ``SafetyCheckResponse`` —
    keeping the detector's return type internal so we can evolve the
    auditing fields without touching the API contract.
    """

    is_emergency: bool
    severity: Literal["critical", "high", "moderate", "low", "info"] | None
    detected_pattern: str | None
    category: EmergencyCategory | None
    stage: Literal["stage_1", "stage_2_llm"] | None
    emergency_response: EmergencyResponse | None


class EmergencyDetector:
    """Implements the two-stage detection algorithm."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        stage_2_enabled: bool | None = None,
        stage_2_model: str = DEFAULT_STAGE_2_MODEL,
        stage_2_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        clear_patterns: tuple[EmergencyPattern, ...] = ALL_CLEAR_PATTERNS,
        ambiguous_patterns: tuple[EmergencyPattern, ...] = ALL_AMBIGUOUS_PATTERNS,
    ) -> None:
        self._llm = llm_client
        # Resolution order: explicit constructor arg → env var → False.
        if stage_2_enabled is None:
            stage_2_enabled = (
                os.environ.get("SAFETY_LLM_CONFIRM_ENABLED", "false").lower() == "true"
            )
        self._stage_2_enabled = stage_2_enabled and llm_client is not None
        self._stage_2_model = stage_2_model
        self._stage_2_timeout = stage_2_timeout_seconds
        self._clear = clear_patterns
        self._ambiguous = ambiguous_patterns

    @property
    def stage_2_enabled(self) -> bool:
        """Effective Stage 2 state (env + LLM client both required)."""
        return self._stage_2_enabled

    async def detect(self, text: str) -> DetectionResult:
        """Run the full pipeline and return a verdict."""
        if not text or not text.strip():
            return _safe_result()

        normalised = normalise_for_matching(text)

        # ─── Stage 1 — clear patterns ────────────────────────────
        clear_hit = self._match_first(normalised, self._clear)
        if clear_hit is not None:
            _log.info(
                "safety.emergency.stage_1_hit",
                pattern=clear_hit.name,
                category=clear_hit.category,
                language=clear_hit.language,
            )
            return DetectionResult(
                is_emergency=True,
                severity="critical",
                detected_pattern=clear_hit.name,
                category=clear_hit.category,
                stage="stage_1",
                emergency_response=build_emergency_response(clear_hit.category),
            )

        # ─── Stage 1.5 — ambiguous patterns ──────────────────────
        ambiguous_hit = self._match_first(normalised, self._ambiguous)
        if ambiguous_hit is None:
            return _safe_result()

        if not self._stage_2_enabled:
            _log.info(
                "safety.ambiguous_unconfirmed",
                pattern=ambiguous_hit.name,
                category=ambiguous_hit.category,
                reason="stage_2_disabled",
            )
            return _safe_result()

        # ─── Stage 2 — LLM confirmation ──────────────────────────
        try:
            confirmed = await self._stage_2_confirm(text)
        except SafetyLLMTimeout:
            # Conservative on timeout: do NOT escalate. The Stage 1
            # patterns are the safety net; Stage 2 is only meant to
            # PROMOTE ambiguous hits, never to be the sole reason
            # for an emergency call.
            _log.warning(
                "safety.stage_2_timeout",
                pattern=ambiguous_hit.name,
            )
            return _safe_result()

        if not confirmed:
            return _safe_result()

        _log.info(
            "safety.emergency.stage_2_hit",
            pattern=ambiguous_hit.name,
            category=ambiguous_hit.category,
        )
        return DetectionResult(
            is_emergency=True,
            severity="critical",
            detected_pattern=ambiguous_hit.name,
            category=ambiguous_hit.category,
            stage="stage_2_llm",
            emergency_response=build_emergency_response(ambiguous_hit.category),
        )

    # ─── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _match_first(
        normalised: str, patterns: tuple[EmergencyPattern, ...]
    ) -> EmergencyPattern | None:
        for pattern in patterns:
            if pattern.regex.search(normalised) is not None:
                return pattern
        return None

    async def _stage_2_confirm(self, text: str) -> bool:
        """Ask the small fast LLM whether this is a current emergency."""
        assert self._llm is not None  # checked by _stage_2_enabled gate
        request = CompletionRequest(
            model=self._stage_2_model,
            messages=(
                Message(role="system", content=DEFAULT_STAGE_2_PROMPT_SYSTEM),
                Message(role="user", content=text),
            ),
            temperature=0.0,
            max_tokens=4,
        )
        try:
            response = await asyncio.wait_for(
                self._llm.complete(request),
                timeout=self._stage_2_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise SafetyLLMTimeout(f"Stage 2 LLM timed out after {self._stage_2_timeout}s") from exc

        verdict = (response.content or "").strip().upper()
        # Accept either "YES" or "YES."/"YES!" etc. — only check the prefix.
        return verdict.startswith("YES")


def _safe_result() -> DetectionResult:
    """Convenience: the not-an-emergency verdict.

    Centralised so any future audit fields are easy to add in one
    place without forgetting one of the return sites.
    """
    return DetectionResult(
        is_emergency=False,
        severity=None,
        detected_pattern=None,
        category=None,
        stage=None,
        emergency_response=None,
    )


__all__ = ["DetectionResult", "EmergencyDetector"]
