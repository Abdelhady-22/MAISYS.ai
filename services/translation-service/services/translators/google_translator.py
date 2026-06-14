"""Google Cloud Translation API adapter.

Lazy import so the service starts cleanly on workstations without
``google-cloud-translate`` installed. The constructor reads the API
key (or project + credentials) from the env; if neither is set, the
adapter still constructs successfully but raises
``TranslationModeUnavailable`` on the first call.

Per Part 1 §7.7 Google is the default mode. We use the v2 REST API
because it accepts an API key directly — the v3 client requires
service-account credentials which add deploy complexity for no
quality gain on simple two-language translation.
"""

from __future__ import annotations

import os

from services.translation_service.exceptions.exceptions import (
    TranslationFailed,
    TranslationModeUnavailable,
)
from services.translation_service.models.schemas import Language, TranslationStyle
from shared.logger import get_logger

_log = get_logger(__name__)


class GoogleTranslator:
    """Adapter for Google Cloud Translation v2 (API-key authenticated)."""

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_TRANSLATE_API_KEY", "")

    async def translate(
        self,
        text: str,
        source_lang: Language,
        target_lang: Language,
        *,
        style: TranslationStyle = "general",  # noqa: ARG002 — ignored by Google mode
    ) -> str:
        if not self._api_key:
            raise TranslationModeUnavailable(
                "Google Translate API key not configured (GOOGLE_TRANSLATE_API_KEY)"
            )

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover — httpx is a base dep
            raise TranslationModeUnavailable(f"httpx not installed: {exc}") from exc

        url = "https://translation.googleapis.com/language/translate/v2"
        params = {
            "key": self._api_key,
            "q": text,
            "source": source_lang,
            "target": target_lang,
            "format": "text",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, params=params)
        except httpx.HTTPError as exc:
            _log.warning("translation.google.http_error", error=str(exc))
            raise TranslationFailed(f"Google Translate HTTP error: {exc}") from exc

        if response.status_code != 200:
            _log.warning(
                "translation.google.non_2xx",
                status_code=response.status_code,
                body=response.text[:200],
            )
            raise TranslationFailed(f"Google Translate returned {response.status_code}")

        try:
            payload = response.json()
            translations = payload["data"]["translations"]
            return str(translations[0]["translatedText"])
        except (KeyError, IndexError, ValueError) as exc:
            raise TranslationFailed(f"Unexpected Google Translate response shape: {exc}") from exc


__all__ = ["GoogleTranslator"]
