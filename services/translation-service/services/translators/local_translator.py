"""Local-fallback translator via the ``deep-translator`` library.

``deep-translator`` wraps Google Translate's public web endpoint —
no API key required. Per Part 1 §7.7 this is the local fallback for
"general text" when you don't want to enable the paid API but still
need okay-quality translation. Quality is similar to Google's
authenticated API for short single-sentence translations; longer
text occasionally hits rate-limits or returns degraded output.

Lazy import — the library isn't a hard dependency. Without it
installed, the adapter raises ``TranslationModeUnavailable`` on first
use.

The ``deep-translator`` call is synchronous — we wrap it with
``asyncio.to_thread`` to keep the orchestrator non-blocking.
"""

from __future__ import annotations

import asyncio

from services.translation_service.exceptions.exceptions import (
    TranslationFailed,
    TranslationModeUnavailable,
)
from services.translation_service.models.schemas import Language, TranslationStyle


class LocalTranslator:
    """``deep-translator`` adapter."""

    async def translate(
        self,
        text: str,
        source_lang: Language,
        target_lang: Language,
        *,
        style: TranslationStyle = "general",  # noqa: ARG002 — ignored
    ) -> str:
        try:
            from deep_translator import GoogleTranslator as _DT
        except ImportError as exc:
            raise TranslationModeUnavailable(f"deep-translator not installed: {exc}") from exc

        translator = _DT(source=source_lang, target=target_lang)
        try:
            return await asyncio.to_thread(translator.translate, text)
        except Exception as exc:
            raise TranslationFailed(f"deep-translator error: {exc}") from exc


__all__ = ["LocalTranslator"]
