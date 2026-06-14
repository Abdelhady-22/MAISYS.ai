"""Translator adapter Protocol + Fake implementation.

The Protocol decouples the orchestrator from any specific provider.
Each concrete translator (``GoogleTranslator``, ``LocalTranslator``,
``LLMTranslator``) implements the same single-method interface so
the orchestrator stays clean.

``FakeTranslator`` is what tests inject — deterministic output,
optional failure-on-Nth-call.
"""

from __future__ import annotations

from typing import Protocol

from services.translation_service.exceptions.exceptions import TranslationFailed
from services.translation_service.models.schemas import (
    Language,
    TranslationStyle,
)


class Translator(Protocol):
    """The single method every translator implements."""

    async def translate(
        self,
        text: str,
        source_lang: Language,
        target_lang: Language,
        *,
        style: TranslationStyle = "general",
    ) -> str:
        """Translate ``text`` from ``source_lang`` to ``target_lang``.

        Raise ``TranslationFailed`` on provider errors. Raise
        ``TranslationModeUnavailable`` (or any subclass of
        ``TranslationServiceException``) for configuration gaps.
        """
        ...


class FakeTranslator:
    """In-memory translator for tests.

    Returns ``"[<src>→<tgt>] <text>"`` so assertions can verify which
    direction was requested. Optional ``fail_first_n`` mirrors the
    FakeEmailAdapter pattern from notification-service so tests can
    exercise error paths without flakiness.
    """

    def __init__(
        self,
        *,
        fail_first_n: int = 0,
        delay_seconds: float = 0.0,
    ) -> None:
        self.calls: list[tuple[str, Language, Language, TranslationStyle]] = []
        self.attempts = 0
        self._fail_first_n = fail_first_n
        self._delay_seconds = delay_seconds

    async def translate(
        self,
        text: str,
        source_lang: Language,
        target_lang: Language,
        *,
        style: TranslationStyle = "general",
    ) -> str:
        self.attempts += 1
        if self._delay_seconds:
            import asyncio

            await asyncio.sleep(self._delay_seconds)
        if self.attempts <= self._fail_first_n:
            raise TranslationFailed(f"Simulated failure on attempt {self.attempts}")
        self.calls.append((text, source_lang, target_lang, style))
        return f"[{source_lang}→{target_lang}] {text}"


__all__ = ["FakeTranslator", "Translator"]
