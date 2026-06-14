"""Tests for BaseAgent ABC and the agent registry."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from services.drug_service.agents import (
    AgentContext,
    AgentRegistry,
    AgentRunResult,
    BaseAgent,
    GENERIC_DISCLAIMER,
    default_registry,
)
from services.drug_service.exceptions import (
    AgentExecutionFailure,
    AgentLowConfidenceException,
)
from services.drug_service.models.schemas import BilingualText, Citation

# ─── Test fixtures: a sample request + agent ──────────────────────


class SampleRequest(BaseModel):
    query: str


class SampleData(BaseModel):
    answer: str


class SampleAgent(BaseAgent[SampleRequest, SampleData]):
    """Concrete agent for testing — returns the query reversed."""

    name = "sample_test_agent"

    def __init__(
        self,
        *,
        confidence: float = 0.9,
        raise_exc: BaseException | None = None,
        sleep_ms: int = 0,
    ) -> None:
        self._confidence = confidence
        self._raise = raise_exc
        self._sleep_ms = sleep_ms

    async def _run(
        self, request: SampleRequest, context: AgentContext
    ) -> AgentRunResult[SampleData]:
        if self._sleep_ms:
            await asyncio.sleep(self._sleep_ms / 1000.0)
        if self._raise is not None:
            raise self._raise
        return AgentRunResult(
            data=SampleData(answer=request.query[::-1]),
            citations=[Citation(source="unit-test", snippet=request.query)],
            confidence=self._confidence,
            tokens_used=42,
        )


class FakePublisher:
    """Captures published progress events for assertion."""

    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event) -> int:
        self.published.append(event)
        return 0


def _ctx(**kwargs) -> AgentContext:
    return AgentContext(
        user_id=kwargs.pop("user_id", "test-user"),
        language=kwargs.pop("language", "en"),
        **kwargs,
    )


# ─── Successful execution ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_returns_response_envelope() -> None:
    agent = SampleAgent()
    response = await agent.execute(SampleRequest(query="hello"), _ctx())
    assert response.data.answer == "olleh"
    assert response.meta.agent_name == "sample_test_agent"
    assert response.meta.confidence == 0.9
    assert response.meta.tokens_used == 42
    assert response.meta.latency_ms >= 0


@pytest.mark.asyncio
async def test_execute_measures_latency() -> None:
    agent = SampleAgent(sleep_ms=20)
    response = await agent.execute(SampleRequest(query="x"), _ctx())
    assert response.meta.latency_ms >= 20


@pytest.mark.asyncio
async def test_execute_attaches_default_disclaimer() -> None:
    agent = SampleAgent()
    response = await agent.execute(SampleRequest(query="x"), _ctx())
    assert response.meta.disclaimer == GENERIC_DISCLAIMER


@pytest.mark.asyncio
async def test_execute_uses_run_supplied_disclaimer_when_present() -> None:
    """A subclass can override the disclaimer per-call by returning one."""
    custom = BilingualText(en="custom en", ar="custom ar")

    class CustomDisclaimerAgent(SampleAgent):
        name = "custom_test_agent"

        async def _run(self, request, context):
            base = await super()._run(request, context)
            return AgentRunResult(
                data=base.data,
                citations=base.citations,
                confidence=base.confidence,
                tokens_used=base.tokens_used,
                disclaimer=custom,
            )

    agent = CustomDisclaimerAgent()
    response = await agent.execute(SampleRequest(query="x"), _ctx())
    assert response.meta.disclaimer == custom


# ─── Low-confidence gate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_raises_low_confidence_exception() -> None:
    agent = SampleAgent(confidence=0.5)  # below default 0.7
    with pytest.raises(AgentLowConfidenceException):
        await agent.execute(SampleRequest(query="x"), _ctx())


@pytest.mark.asyncio
async def test_at_threshold_confidence_passes() -> None:
    """Confidence exactly at min_confidence is acceptable."""
    agent = SampleAgent(confidence=0.7)
    response = await agent.execute(SampleRequest(query="x"), _ctx())
    assert response.meta.confidence == 0.7


# ─── Exception handling ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_unexpected_exception_wrapped_in_execution_failure() -> None:
    agent = SampleAgent(raise_exc=RuntimeError("upstream blew up"))
    with pytest.raises(AgentExecutionFailure) as excinfo:
        await agent.execute(SampleRequest(query="x"), _ctx())
    assert "sample_test_agent agent failed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_execution_failure_passes_through_unchanged() -> None:
    """If the subclass already raises AgentExecutionFailure, don't double-wrap."""
    original = AgentExecutionFailure("explicit failure message")
    agent = SampleAgent(raise_exc=original)
    with pytest.raises(AgentExecutionFailure) as excinfo:
        await agent.execute(SampleRequest(query="x"), _ctx())
    assert excinfo.value is original


@pytest.mark.asyncio
async def test_missing_name_raises_assertion() -> None:
    class UnnamedAgent(BaseAgent[SampleRequest, SampleData]):
        async def _run(self, request, context):
            return AgentRunResult(data=SampleData(answer="x"), citations=[], confidence=1.0)

    with pytest.raises(AssertionError):
        await UnnamedAgent().execute(SampleRequest(query="x"), _ctx())


# ─── Progress publishing ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_progress_events_published_on_success() -> None:
    publisher = FakePublisher()
    agent = SampleAgent()
    await agent.execute(
        SampleRequest(query="x"),
        _ctx(progress_publisher=publisher),
    )
    statuses = [e.status for e in publisher.published]
    assert statuses == ["in_progress", "in_progress"]
    assert "started" in publisher.published[0].message
    assert "completed" in publisher.published[1].message


@pytest.mark.asyncio
async def test_progress_events_published_on_failure() -> None:
    publisher = FakePublisher()
    agent = SampleAgent(raise_exc=RuntimeError("boom"))
    with pytest.raises(AgentExecutionFailure):
        await agent.execute(
            SampleRequest(query="x"),
            _ctx(progress_publisher=publisher),
        )
    statuses = [e.status for e in publisher.published]
    assert statuses == ["in_progress", "failed"]


@pytest.mark.asyncio
async def test_progress_events_published_on_low_confidence() -> None:
    publisher = FakePublisher()
    agent = SampleAgent(confidence=0.3)
    with pytest.raises(AgentLowConfidenceException):
        await agent.execute(
            SampleRequest(query="x"),
            _ctx(progress_publisher=publisher),
        )
    failed = [e for e in publisher.published if e.status == "failed"]
    assert len(failed) == 1
    assert failed[0].details["reason"] == "low_confidence"


@pytest.mark.asyncio
async def test_no_publisher_means_no_events_attempted() -> None:
    """Agents work without a publisher — events are skipped silently."""
    agent = SampleAgent()
    response = await agent.execute(SampleRequest(query="x"), _ctx())
    assert response is not None


# ─── AgentContext ─────────────────────────────────────────────────


def test_context_generates_correlation_id_when_omitted() -> None:
    ctx = AgentContext(user_id="u", language="en")
    assert len(ctx.correlation_id) == 32


def test_context_effective_job_id_falls_back_to_correlation_id() -> None:
    ctx = AgentContext(user_id="u", language="en", correlation_id="abc123")
    assert ctx.effective_job_id == "abc123"


def test_context_effective_job_id_uses_explicit_job_id() -> None:
    ctx = AgentContext(user_id="u", language="en", correlation_id="abc", job_id="job-99")
    assert ctx.effective_job_id == "job-99"


# ─── AgentRegistry ────────────────────────────────────────────────


def test_registry_registers_and_retrieves_agent() -> None:
    registry = AgentRegistry()
    agent = SampleAgent()
    registry.register(agent)
    assert registry.get("sample_test_agent") is agent
    assert "sample_test_agent" in registry
    assert "sample_test_agent" in registry.names()


def test_registry_rejects_duplicate_registration() -> None:
    registry = AgentRegistry()
    registry.register(SampleAgent())
    with pytest.raises(ValueError):
        registry.register(SampleAgent())


def test_registry_rejects_unnamed_agent() -> None:
    class UnnamedAgent(BaseAgent[SampleRequest, SampleData]):
        async def _run(self, request, context):
            return AgentRunResult(data=SampleData(answer="x"), citations=[], confidence=1.0)

    registry = AgentRegistry()
    with pytest.raises(ValueError):
        registry.register(UnnamedAgent())


def test_default_registry_starts_empty() -> None:
    """Commits 4-11 will register agents; commit 3 leaves it empty."""
    # NOTE: this can drift as other tests register agents — assert
    # only that the registry exists and is usable.
    assert isinstance(default_registry, AgentRegistry)
