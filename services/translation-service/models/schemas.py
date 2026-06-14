"""Pydantic schemas for translation-service.

Per Part 1 §7.7 the service is stateless with a Redis cache. The
request shape mirrors the three configurable modes (``google`` /
``local`` / ``llm``) and an optional ``style`` field used by the LLM
mode to pick a per-module prompt (chatbot conversational, lab
clinical, etc.). ``style`` is ignored by the non-LLM modes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["ar", "en"]
SourceLanguage = Literal["ar", "en", "auto"]
TranslationMode = Literal["google", "local", "llm"]
TranslationStyle = Literal["general", "clinical", "conversational"]


# ─── /translate ──────────────────────────────────────────────────


class TranslateRequest(BaseModel):
    """Body of ``POST /translate``."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)
    source_lang: SourceLanguage = "auto"
    target_lang: Language
    mode: TranslationMode = "google"
    """Default per Part 1 §7.7. LLM mode for medical terminology."""

    style: TranslationStyle = "general"
    """Applied only when ``mode == 'llm'``. Picks the per-module
    prompt — ignored otherwise."""


class TranslateResponse(BaseModel):
    """Body returned by ``POST /translate``."""

    model_config = ConfigDict(extra="forbid")

    translated_text: str
    source_lang_detected: Language
    """The actual source language used. If the caller passed
    ``source_lang='auto'`` this is the detected value; otherwise it
    matches what the caller sent."""

    target_lang: Language
    mode_used: TranslationMode
    cached: bool
    """True when the response was served from the Redis cache."""


# ─── /translate/batch ────────────────────────────────────────────


class BatchTranslateRequest(BaseModel):
    """Body of ``POST /translate/batch``.

    The batch endpoint runs each request independently — partial
    failures don't abort the batch. Each item in the response carries
    its own ``cached`` flag and the same shape as the single
    endpoint's response, plus an ``error`` field set when that single
    item failed.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[TranslateRequest] = Field(min_length=1, max_length=50)


class BatchItemError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class BatchTranslateItem(BaseModel):
    """One entry in the batch response — either a success or an error."""

    model_config = ConfigDict(extra="forbid")

    translated_text: str | None = None
    source_lang_detected: Language | None = None
    target_lang: Language | None = None
    mode_used: TranslationMode | None = None
    cached: bool = False
    error: BatchItemError | None = None


class BatchTranslateResponse(BaseModel):
    """Body returned by ``POST /translate/batch``."""

    model_config = ConfigDict(extra="forbid")

    items: list[BatchTranslateItem]


__all__ = [
    "BatchItemError",
    "BatchTranslateItem",
    "BatchTranslateRequest",
    "BatchTranslateResponse",
    "Language",
    "SourceLanguage",
    "TranslateRequest",
    "TranslateResponse",
    "TranslationMode",
    "TranslationStyle",
]
