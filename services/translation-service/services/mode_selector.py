"""Mode selector — maps mode name → translator instance.

The selector is built once at startup with the translators that are
actually wired in. If a caller requests a mode that wasn't wired
(missing API key, missing SDK), the selector raises
``TranslationModeUnavailable`` so callers see a clean 503 rather
than a generic 500.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.translation_service.exceptions.exceptions import (
    TranslationModeUnavailable,
)
from services.translation_service.models.schemas import TranslationMode
from services.translation_service.services.translators.protocol import Translator


@dataclass(frozen=True)
class ModeSelector:
    """Holds one optional translator per mode."""

    google: Translator | None = None
    local: Translator | None = None
    llm: Translator | None = None

    def get(self, mode: TranslationMode) -> Translator:
        candidate = {
            "google": self.google,
            "local": self.local,
            "llm": self.llm,
        }[mode]
        if candidate is None:
            raise TranslationModeUnavailable(
                f"Translation mode {mode!r} is not configured on this instance"
            )
        return candidate

    def available_modes(self) -> list[TranslationMode]:
        """List the modes that are usable on this instance.

        Used by the readiness check and surfaced in logs at startup
        so deploy mistakes are visible immediately.
        """
        out: list[TranslationMode] = []
        if self.google is not None:
            out.append("google")
        if self.local is not None:
            out.append("local")
        if self.llm is not None:
            out.append("llm")
        return out


__all__ = ["ModeSelector"]
