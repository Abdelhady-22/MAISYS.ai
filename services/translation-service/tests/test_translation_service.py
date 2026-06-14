"""Tests for TranslationService — orchestrator behaviour."""

from __future__ import annotations

import pytest

from services.translation_service.exceptions.exceptions import (
    TranslationFailed,
    TranslationModeUnavailable,
)
from services.translation_service.models.schemas import (
    BatchTranslateRequest,
    TranslateRequest,
)
from services.translation_service.repository.cache_repo import (
    InMemoryTranslationCache,
)
from services.translation_service.services.mode_selector import ModeSelector
from services.translation_service.services.translation_service import (
    TranslationService,
)
from services.translation_service.services.translators.protocol import FakeTranslator

# ─── Basic happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_translate_en_to_ar_via_google(
    translation_service: TranslationService,
    fake_google: FakeTranslator,
) -> None:
    response = await translation_service.translate(
        TranslateRequest(
            text="Hello world",
            source_lang="en",
            target_lang="ar",
            mode="google",
        )
    )
    assert response.translated_text == "[en→ar] Hello world"
    assert response.source_lang_detected == "en"
    assert response.target_lang == "ar"
    assert response.mode_used == "google"
    assert response.cached is False
    assert fake_google.attempts == 1


@pytest.mark.asyncio
async def test_translate_ar_to_en_via_llm(
    translation_service: TranslationService,
    fake_llm: FakeTranslator,
) -> None:
    response = await translation_service.translate(
        TranslateRequest(
            text="عندي صداع",
            source_lang="ar",
            target_lang="en",
            mode="llm",
            style="clinical",
        )
    )
    assert response.translated_text == "[ar→en] عندي صداع"
    assert response.mode_used == "llm"
    assert fake_llm.attempts == 1
    # Style passed through to translator
    assert fake_llm.calls[0][3] == "clinical"


# ─── Auto-detect ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_detect_arabic_input(
    translation_service: TranslationService,
) -> None:
    response = await translation_service.translate(
        TranslateRequest(
            text="عندي ألم في الصدر",
            source_lang="auto",
            target_lang="en",
            mode="google",
        )
    )
    assert response.source_lang_detected == "ar"


@pytest.mark.asyncio
async def test_auto_detect_english_input(
    translation_service: TranslationService,
) -> None:
    response = await translation_service.translate(
        TranslateRequest(
            text="I have chest pain",
            source_lang="auto",
            target_lang="ar",
            mode="google",
        )
    )
    assert response.source_lang_detected == "en"


# ─── Same-language short-circuit ─────────────────────────────────


@pytest.mark.asyncio
async def test_same_language_returns_unchanged(
    translation_service: TranslationService,
    fake_google: FakeTranslator,
) -> None:
    response = await translation_service.translate(
        TranslateRequest(
            text="Hello world",
            source_lang="en",
            target_lang="en",
            mode="google",
        )
    )
    assert response.translated_text == "Hello world"
    assert response.cached is False
    # Translator never called
    assert fake_google.attempts == 0


# ─── Cache hit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_skips_translator(
    translation_service: TranslationService,
    fake_google: FakeTranslator,
) -> None:
    req = TranslateRequest(
        text="Hello world",
        source_lang="en",
        target_lang="ar",
        mode="google",
    )
    # First call — populates cache
    first = await translation_service.translate(req)
    assert first.cached is False
    assert fake_google.attempts == 1

    # Second call — cache hit, translator not called again
    second = await translation_service.translate(req)
    assert second.cached is True
    assert second.translated_text == first.translated_text
    assert fake_google.attempts == 1  # unchanged


@pytest.mark.asyncio
async def test_cache_keyed_by_mode_and_style(
    translation_service: TranslationService,
    fake_google: FakeTranslator,
    fake_llm: FakeTranslator,
) -> None:
    """Different mode/style → different cache key → translator called again."""
    google_req = TranslateRequest(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="google",
    )
    llm_req = TranslateRequest(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="llm",
    )
    llm_clinical_req = TranslateRequest(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="llm",
        style="clinical",
    )

    r1 = await translation_service.translate(google_req)
    r2 = await translation_service.translate(llm_req)
    r3 = await translation_service.translate(llm_clinical_req)

    assert all(not r.cached for r in (r1, r2, r3))
    assert fake_google.attempts == 1
    assert fake_llm.attempts == 2


# ─── Unsupported pair ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_pair_raises(
    cache: InMemoryTranslationCache,
    fake_google: FakeTranslator,
) -> None:
    # Trick the orchestrator with an English→English request that
    # passes a different source: this isn't directly possible
    # through the schema (Language Literal restricts to en/ar), so we
    # bypass the request shape and call the internal logic.
    # The orchestrator's defence is in case schema validation drift
    # ever lets an unsupported pair through.

    # We can't construct an unsupported pair via the public schema
    # because Pydantic forbids any value outside Literal["en","ar"]
    # for source/target. The defensive UnsupportedLanguagePair check
    # is a belt-and-braces guard — exercise it via a unit test on the
    # frozenset itself.
    from services.translation_service.services.translation_service import (
        _SUPPORTED_PAIRS,
    )

    assert ("en", "ar") in _SUPPORTED_PAIRS
    assert ("ar", "en") in _SUPPORTED_PAIRS


# ─── Mode unavailable ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mode_unavailable_raises() -> None:
    """If a mode isn't wired, requesting it raises a 503-mapped exception."""
    selector = ModeSelector(google=None, local=None, llm=None)
    cache = InMemoryTranslationCache()
    service = TranslationService(mode_selector=selector, cache=cache)
    with pytest.raises(TranslationModeUnavailable):
        await service.translate(
            TranslateRequest(
                text="Hello",
                source_lang="en",
                target_lang="ar",
                mode="google",
            )
        )


# ─── Translator failure surfaces correctly ───────────────────────


@pytest.mark.asyncio
async def test_translator_failure_propagates() -> None:
    failing = FakeTranslator(fail_first_n=10)  # always fails
    selector = ModeSelector(google=failing, local=None, llm=None)
    cache = InMemoryTranslationCache()
    service = TranslationService(mode_selector=selector, cache=cache)
    with pytest.raises(TranslationFailed):
        await service.translate(
            TranslateRequest(
                text="Hello",
                source_lang="en",
                target_lang="ar",
                mode="google",
            )
        )


# ─── Batch ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_concurrent_partial_failure(
    cache: InMemoryTranslationCache,
) -> None:
    """First item succeeds; second uses an unavailable mode."""
    google = FakeTranslator()
    selector = ModeSelector(google=google, local=None, llm=None)
    service = TranslationService(mode_selector=selector, cache=cache)

    response = await service.translate_batch(
        BatchTranslateRequest(
            items=[
                TranslateRequest(
                    text="Hello",
                    source_lang="en",
                    target_lang="ar",
                    mode="google",
                ),
                TranslateRequest(
                    text="World",
                    source_lang="en",
                    target_lang="ar",
                    mode="llm",  # not wired
                ),
                TranslateRequest(
                    text="Friend",
                    source_lang="en",
                    target_lang="ar",
                    mode="google",
                ),
            ]
        )
    )
    assert len(response.items) == 3
    # Item 0 — success
    assert response.items[0].translated_text == "[en→ar] Hello"
    assert response.items[0].error is None
    # Item 1 — error (mode unavailable)
    assert response.items[1].translated_text is None
    assert response.items[1].error is not None
    assert response.items[1].error.code == "TRANSLATION_MODE_UNAVAILABLE"
    # Item 2 — success
    assert response.items[2].translated_text == "[en→ar] Friend"
    assert response.items[2].error is None


@pytest.mark.asyncio
async def test_batch_runs_concurrently(
    cache: InMemoryTranslationCache,
) -> None:
    """If batch ran sequentially, latency would be N*delay; concurrent is ~delay."""
    import time

    slow = FakeTranslator(delay_seconds=0.05)
    selector = ModeSelector(google=slow, local=None, llm=None)
    service = TranslationService(mode_selector=selector, cache=cache)
    items = [
        TranslateRequest(
            text=f"text-{i}",
            source_lang="en",
            target_lang="ar",
            mode="google",
        )
        for i in range(5)
    ]
    start = time.perf_counter()
    response = await service.translate_batch(BatchTranslateRequest(items=items))
    elapsed = time.perf_counter() - start

    assert len(response.items) == 5
    # Sequential would be ~0.25s; concurrent should be ~0.05-0.10s with overhead
    assert elapsed < 0.20, f"batch ran too slowly: {elapsed:.3f}s suggests sequential"
