"""LLM-based translator using ``shared/llm_client``.

Per Part 1 §7.7 the LLM mode is recommended for medical terminology
where the other modes would distort clinical meaning. The system
prompt is varied by ``style`` so the same caller can request
conversational tone for chatbot output or clinical tone for lab
explanations.

Generic drug names (warfarin, ibuprofen, paracetamol) are kept in
English even within Arabic output — that's a clinical-communication
norm in Egypt and the Gulf, and machine translations that
"localise" them often produce inaccurate transliterations.
"""

from __future__ import annotations

from services.translation_service.exceptions.exceptions import TranslationFailed
from services.translation_service.models.schemas import (
    Language,
    TranslationStyle,
)
from shared.llm_client import CompletionRequest, LLMClient, Message
from shared.logger import get_logger

_log = get_logger(__name__)


_BASE_INSTRUCTION = (
    "You are a medical translation engine for the MAISYS platform. "
    "Translate the user-provided text from {source} to {target}. "
    "Preserve generic drug names in English even when translating to Arabic "
    "(e.g. write 'warfarin' in English mid-sentence rather than transliterating). "
    "Preserve numeric values, units, and dosing schedules exactly as written. "
    "Output ONLY the translated text — no preamble, no quotes, no commentary."
)

_STYLE_GUIDANCE: dict[TranslationStyle, str] = {
    "general": "Use natural everyday phrasing.",
    "clinical": (
        "Use the register of patient education materials — accurate, neutral, "
        "and accessible without being childish."
    ),
    "conversational": (
        "Use a warm conversational register suited to a chat interface. " "Keep sentences short."
    ),
}

_LANG_NAMES: dict[Language, str] = {"en": "English", "ar": "Arabic"}


class LLMTranslator:
    """LLM translator. Constructor takes an ``LLMClient``."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
    ) -> None:
        self._llm = llm_client
        self._model = model

    async def translate(
        self,
        text: str,
        source_lang: Language,
        target_lang: Language,
        *,
        style: TranslationStyle = "general",
    ) -> str:
        system_prompt = (
            _BASE_INSTRUCTION.format(
                source=_LANG_NAMES[source_lang],
                target=_LANG_NAMES[target_lang],
            )
            + " "
            + _STYLE_GUIDANCE[style]
        )
        try:
            response = await self._llm.complete(
                CompletionRequest(
                    model=self._model,
                    messages=(
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=text),
                    ),
                    temperature=0.2,
                    max_tokens=2048,
                )
            )
        except Exception as exc:
            _log.warning("translation.llm.error", error=str(exc))
            raise TranslationFailed(f"LLM translation failed: {exc}") from exc

        out = (response.content or "").strip()
        if not out:
            raise TranslationFailed("LLM returned empty translation")
        return out


__all__ = ["LLMTranslator"]
