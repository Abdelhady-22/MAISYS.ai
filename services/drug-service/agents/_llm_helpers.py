"""LLM helper utilities shared across drug-service agents.

The 8 agents in commits 4-11 all follow the same pattern: send a
prompt to ``shared.llm_client.LLMClient``, parse the response into a
Pydantic schema, retry once on malformed JSON. This module centralises
that pattern so individual agent files stay focused on domain logic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from services.drug_service.exceptions import AgentExecutionFailure
from services.drug_service.models.schemas import Language
from shared.llm_client import CompletionRequest, LLMClient, Message
from shared.logger import get_logger

_log = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


_PROMPT_CACHE: dict[Path, str] = {}


def load_prompt(prompts_dir: Path, agent_name: str, language: Language) -> str:
    """Load and cache a prompt template from ``<dir>/<agent>_{lang}.txt``."""
    path = prompts_dir / f"{agent_name}_{language}.txt"
    if path not in _PROMPT_CACHE:
        if not path.exists():
            raise AgentExecutionFailure(f"Prompt template not found: {path}")
        _PROMPT_CACHE[path] = path.read_text(encoding="utf-8")
    return _PROMPT_CACHE[path]


def format_prompt(template: str, **variables: object) -> str:
    """Format a prompt template with the given variables.

    Uses ``str.format``. Variables not present in the template are
    ignored; missing variables raise ``KeyError``.
    """
    return template.format(**variables)


def extract_json_object(text: str) -> str:
    """Best-effort extraction of a top-level JSON object from an LLM response.

    LiteLLM with ``response_format={"type": "json_object"}`` returns
    pure JSON; older models or providers may wrap the JSON in
    markdown fences or chatty prose. This handles both:

    * ``{"key": "value"}``
    * ``Here is the JSON:\\n```json\\n{...}\\n``` `` (markdown-fenced)
    * ``Some preamble. {"key": "value"} Some postscript.``
    """
    stripped = text.strip()

    # Direct JSON object
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    # Markdown fence
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        return fenced.group(1)

    # First {...} block
    brace = re.search(r"(\{.*\})", stripped, re.DOTALL)
    if brace:
        return brace.group(1)

    raise AgentExecutionFailure(f"No JSON object found in LLM response: {text[:200]!r}")


async def synthesise_json(
    *,
    llm_client: LLMClient,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema: type[SchemaT],
    max_tokens: int = 800,
    temperature: float = 0.2,
) -> tuple[SchemaT, int]:
    """Run a JSON-mode completion and parse the result into ``schema``.

    Retries once on JSON parse failure with a stricter system message;
    after that, raises ``AgentExecutionFailure``.

    Returns the parsed schema instance and the total token count.
    """
    request = CompletionRequest(
        model=model,
        messages=(
            Message("system", system_prompt),
            Message("user", user_prompt),
        ),
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    response = await llm_client.complete(request)
    parsed, tokens = _try_parse(response.content, schema, response.usage.total_tokens)
    if parsed is not None:
        return parsed, tokens

    # Retry once with a tighter instruction
    _log.warning("agent.llm.retry_after_parse_failure", model=model)
    retry_request = CompletionRequest(
        model=model,
        messages=(
            Message(
                "system",
                system_prompt
                + "\n\nThe previous response was not valid JSON matching the required schema. "
                + "Return ONLY a JSON object, no prose, no markdown fences.",
            ),
            Message("user", user_prompt),
        ),
        temperature=0.0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    retry_response = await llm_client.complete(retry_request)
    parsed_retry, retry_tokens = _try_parse(
        retry_response.content, schema, retry_response.usage.total_tokens
    )
    if parsed_retry is not None:
        return parsed_retry, tokens + retry_tokens

    raise AgentExecutionFailure("LLM response did not match the expected schema after retry")


def _try_parse(raw: str, schema: type[SchemaT], tokens: int) -> tuple[SchemaT | None, int]:
    try:
        json_text = extract_json_object(raw)
        payload = json.loads(json_text)
        return schema.model_validate(payload), tokens
    except (json.JSONDecodeError, ValidationError, AgentExecutionFailure) as exc:
        _log.info("agent.llm.parse_attempt_failed", error=str(exc)[:200])
        return None, tokens


__all__ = [
    "extract_json_object",
    "format_prompt",
    "load_prompt",
    "synthesise_json",
]
