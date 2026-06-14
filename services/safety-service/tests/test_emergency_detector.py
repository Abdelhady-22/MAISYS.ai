"""Tests for ``EmergencyDetector`` — Stage 1, Stage 2, normalisation."""

from __future__ import annotations

import asyncio

import pytest

from services.safety_service.services.emergency_detector import EmergencyDetector
from shared.llm_client import FakeLLMBackend, FakeResponse, LLMClient

# ─── Stage 1 — clear English patterns ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text, expected_category",
    [
        ("I have chest pain and it's getting worse", "cardiac"),
        ("My chest hurts so bad", "cardiac"),
        ("I can't breathe", "respiratory"),
        ("I think I'm having a stroke", "stroke"),
        ("He just collapsed and is unresponsive", "loss_of_consciousness"),
        ("My son is having a seizure right now", "seizure"),
        ("There's severe bleeding from her arm", "bleeding"),
        ("I think this is anaphylaxis my throat is closing", "allergic"),
        ("I took an overdose of my pills", "overdose"),
        ("I'm suicidal and need help", "mental_health_crisis"),
        ("I think I'm having a heart attack", "cardiac"),
        ("My child swallowed my medication", "ingestion"),
        ("Call 911 we need an ambulance now", "unspecified"),
    ],
)
async def test_stage_1_english_clear_patterns_match(text: str, expected_category: str) -> None:
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect(text)
    assert result.is_emergency is True
    assert result.category == expected_category
    assert result.stage == "stage_1"
    assert result.emergency_response is not None


# ─── Stage 1 — clear Arabic patterns ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text, expected_category",
    [
        ("عندي ألم في الصدر شديد", "cardiac"),
        ("ما أقدر أتنفس أبداً", "respiratory"),
        ("أعتقد عندي سكتة دماغية", "stroke"),
        ("فقدان الوعي بشكل مفاجئ", "loss_of_consciousness"),
        ("عندي نوبة صرع الآن", "seizure"),
        ("نزيف حاد من رأسه", "bleeding"),
        ("حساسية شديدة وتورم الحلق", "allergic"),
        ("أخذت جرعة زائدة من الدواء", "overdose"),
        ("عندي أفكار انتحارية", "mental_health_crisis"),
        ("أزمة قلبية", "cardiac"),
    ],
)
async def test_stage_1_arabic_clear_patterns_match(text: str, expected_category: str) -> None:
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect(text)
    assert result.is_emergency is True, f"Expected match for: {text}"
    assert result.category == expected_category
    assert result.stage == "stage_1"


# ─── Normalisation — diacritics, hamza, whitespace ───────────────


@pytest.mark.asyncio
async def test_arabic_normalisation_strips_diacritics() -> None:
    """Text with full harakat should match the bare pattern."""
    # 'ألم في الصدر' fully voweled
    text = "أَلَمٌ فِي الصَّدْرِ"
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect(text)
    assert result.is_emergency is True


@pytest.mark.asyncio
async def test_normalisation_handles_hamza_variants() -> None:
    # 'أزمة قلبية' uses أ; matching pattern should also catch 'ازمة قلبية'
    detector = EmergencyDetector(stage_2_enabled=False)
    result_with = await detector.detect("أزمة قلبية")
    result_without = await detector.detect("ازمة قلبية")
    assert result_with.is_emergency is True
    assert result_without.is_emergency is True


@pytest.mark.asyncio
async def test_normalisation_collapses_whitespace() -> None:
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect("I    have    chest   pain")
    assert result.is_emergency is True


# ─── Safe inputs — should NOT match ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "What is the recommended dose of ibuprofen?",
        "Can you explain how aspirin works?",
        "I want to know more about blood pressure",
        "ما هي جرعة الباراسيتامول للأطفال",
        "أريد أن أعرف عن ضغط الدم",
        "Hello, how are you?",
        "",
        "   ",
    ],
)
async def test_safe_inputs_do_not_trigger(text: str) -> None:
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect(text)
    assert result.is_emergency is False
    assert result.emergency_response is None


# ─── Stage 1.5 — ambiguous without Stage 2 → not emergency ───────


@pytest.mark.asyncio
async def test_ambiguous_pattern_without_stage_2_is_not_emergency() -> None:
    """'chest pain' as a topic — no first-person framing — falls through."""
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect("I read an article about chest pain causes")
    assert result.is_emergency is False


# ─── Stage 2 — LLM confirmation ──────────────────────────────────


@pytest.mark.asyncio
async def test_stage_2_yes_confirms_emergency() -> None:
    backend = FakeLLMBackend()
    backend.queue(FakeResponse(content="YES", prompt_tokens=20, completion_tokens=1))
    llm = LLMClient(backend=backend)
    detector = EmergencyDetector(llm_client=llm, stage_2_enabled=True)
    result = await detector.detect("Reading about chest pain and what it means")
    assert result.is_emergency is True
    assert result.stage == "stage_2_llm"


@pytest.mark.asyncio
async def test_stage_2_no_keeps_safe() -> None:
    backend = FakeLLMBackend()
    backend.queue(FakeResponse(content="NO", prompt_tokens=20, completion_tokens=1))
    llm = LLMClient(backend=backend)
    detector = EmergencyDetector(llm_client=llm, stage_2_enabled=True)
    result = await detector.detect("I read about chest pain causes")
    assert result.is_emergency is False


@pytest.mark.asyncio
async def test_stage_2_timeout_does_not_escalate() -> None:
    """If Stage 2 times out, the verdict is safe (conservative)."""

    class SlowBackend(FakeLLMBackend):
        async def complete(self, request):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.5)
            return FakeResponse(content="YES", prompt_tokens=20, completion_tokens=1)

    llm = LLMClient(backend=SlowBackend())
    detector = EmergencyDetector(
        llm_client=llm,
        stage_2_enabled=True,
        stage_2_timeout_seconds=0.05,
    )
    result = await detector.detect("chest pain topic")
    assert result.is_emergency is False


# ─── Emergency response payload shape ────────────────────────────


@pytest.mark.asyncio
async def test_emergency_response_payload_has_bilingual_fields() -> None:
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect("I am having a heart attack")
    assert result.emergency_response is not None
    er = result.emergency_response
    # Title is the warning emoji + bilingual phrase
    assert "emergency" in er.title_en.lower()
    assert "طوارئ" in er.title_ar
    assert len(er.actions_en) > 0
    assert len(er.actions_ar) > 0
    assert er.do_not_wait is True
    assert er.session_should_halt is True


@pytest.mark.asyncio
async def test_mental_health_crisis_uses_specific_message() -> None:
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect("I'm suicidal")
    assert result.category == "mental_health_crisis"
    assert result.emergency_response is not None
    # The mental-health message specifically references "thoughts of suicide or self-harm"
    assert (
        "suicide" in result.emergency_response.message_en.lower()
        or "self-harm" in result.emergency_response.message_en.lower()
    )
    assert (
        "انتحار" in result.emergency_response.message_ar
        or "إيذاء" in result.emergency_response.message_ar
    )


# ─── Critical false-negative cases (Part 4 target: 0%) ────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        # Phrased in different ways — none must slip through
        "I have crushing chest pressure",
        "She passed out and is not responding",
        "He took too many pills",
        "I want to die today",
        "I just took an overdose",
        "my baby swallowed bleach",
    ],
)
async def test_critical_no_false_negatives(text: str) -> None:
    """Cases where missing the emergency would be unforgivable."""
    detector = EmergencyDetector(stage_2_enabled=False)
    result = await detector.detect(text)
    assert result.is_emergency is True, f"FALSE NEGATIVE on: {text!r}"
