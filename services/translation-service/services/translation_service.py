"""TranslationService — the service-layer orchestrator.

For each request:

1. Resolve the source language (auto-detect if not specified)
2. Short-circuit when source == target (return text as-is, ``cached=False``)
3. Reject unsupported pairs
4. Build cache key, check cache, return hit if present
5. Dispatch to the requested translator
6. Store in cache, return

The orchestrator never raises ``TranslationFailed`` to callers
directly — that's the route layer's job to map to an HTTP response.
This class just calls the underlying methods.
"""

from __future__ import annotations

import asyncio

from services.translation_service.exceptions.exceptions import (
    UnsupportedLanguagePair,
)
from services.translation_service.models.schemas import (
    BatchItemError,
    BatchTranslateItem,
    BatchTranslateRequest,
    BatchTranslateResponse,
    Language,
    TranslateRequest,
    TranslateResponse,
)
from services.translation_service.repository.cache_repo import (
    TranslationCache,
    make_cache_key,
)
from services.translation_service.services.lang_detector import detect_language
from services.translation_service.services.mode_selector import ModeSelector
from shared.logger import get_logger

_log = get_logger(__name__)

_SUPPORTED_PAIRS: frozenset[tuple[Language, Language]] = frozenset({("en", "ar"), ("ar", "en")})


class TranslationService:
    """Single instance per service. Safe to share across requests."""

    def __init__(
        self,
        *,
        mode_selector: ModeSelector,
        cache: TranslationCache,
    ) -> None:
        self._selector = mode_selector
        self._cache = cache

    async def translate(self, request: TranslateRequest) -> TranslateResponse:
        source = self._resolve_source(request)
        target = request.target_lang

        # Same language — return unchanged. Don't even hit the cache.
        if source == target:
            return TranslateResponse(
                translated_text=request.text,
                source_lang_detected=source,
                target_lang=target,
                mode_used=request.mode,
                cached=False,
            )

        if (source, target) not in _SUPPORTED_PAIRS:
            raise UnsupportedLanguagePair(f"Unsupported translation pair: {source} → {target}")

        cache_key = make_cache_key(
            text=request.text,
            source_lang=source,
            target_lang=target,
            mode=request.mode,
            style=request.style,
        )
        cached_text = await self._cache.get(cache_key)
        if cached_text is not None:
            _log.info("translation.cache_hit", source=source, target=target, mode=request.mode)
            return TranslateResponse(
                translated_text=cached_text,
                source_lang_detected=source,
                target_lang=target,
                mode_used=request.mode,
                cached=True,
            )

        translator = self._selector.get(request.mode)
        translated = await translator.translate(request.text, source, target, style=request.style)

        await self._cache.set(cache_key, translated)
        _log.info(
            "translation.served",
            source=source,
            target=target,
            mode=request.mode,
            style=request.style,
            cached=False,
        )
        return TranslateResponse(
            translated_text=translated,
            source_lang_detected=source,
            target_lang=target,
            mode_used=request.mode,
            cached=False,
        )

    async def translate_batch(self, request: BatchTranslateRequest) -> BatchTranslateResponse:
        """Translate each item independently — partial failures don't abort.

        Runs items concurrently; results are returned in the input
        order regardless of completion order.
        """
        coros = [self._translate_one_safe(item) for item in request.items]
        items = await asyncio.gather(*coros)
        return BatchTranslateResponse(items=items)

    async def _translate_one_safe(self, request: TranslateRequest) -> BatchTranslateItem:
        from services.translation_service.exceptions.exceptions import (
            TranslationServiceException,
        )

        try:
            response = await self.translate(request)
        except TranslationServiceException as exc:
            return BatchTranslateItem(
                error=BatchItemError(code=exc.code, message=str(exc)),
            )
        return BatchTranslateItem(
            translated_text=response.translated_text,
            source_lang_detected=response.source_lang_detected,
            target_lang=response.target_lang,
            mode_used=response.mode_used,
            cached=response.cached,
        )

    @staticmethod
    def _resolve_source(request: TranslateRequest) -> Language:
        if request.source_lang == "auto":
            return detect_language(request.text)
        return request.source_lang


__all__ = ["TranslationService"]
