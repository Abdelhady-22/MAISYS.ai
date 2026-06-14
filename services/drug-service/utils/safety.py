"""Safety hook — best-effort self-harm / overdose detection.

The brief calls for every dosage / interaction / contraindication
response to be safety-checked against an upstream ``safety-service``.
That service doesn't exist yet (it's a later phase). This module
provides the call surface today so:

* Every agent response flows through ``check_query_safety()``.
* If the service is reachable, the response is gated on its verdict.
* If the service returns 404 (because it doesn't exist) or is
  unreachable, we log it and continue — never fail the user request
  for a missing dependency.
* When the service IS deployed in a later phase, this module needs
  no changes; the call surface stays stable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from services.drug_service.exceptions import SelfHarmDetectedException
from shared.logger import get_logger

_log = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class SafetyConfig:
    base_url: str
    enabled: bool
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> SafetyConfig:
        return cls(
            base_url=os.environ.get("SAFETY_SERVICE_URL", "http://safety-service:8003"),
            enabled=os.environ.get("SAFETY_SERVICE_ENABLED", "true").lower() == "true",
        )


async def check_query_safety(
    query_text: str,
    *,
    user_id: str,
    correlation_id: str,
    config: SafetyConfig | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Raise ``SelfHarmDetectedException`` if the safety service flags the query.

    Pass-through behaviour when the service is missing, disabled, or
    unreachable — by design. We do NOT block on a missing safety
    service; otherwise the drug service would be unusable until
    safety-service is built.
    """
    cfg = config or SafetyConfig.from_env()
    if not cfg.enabled:
        return

    client = http_client or httpx.AsyncClient(timeout=cfg.timeout_seconds)
    owns_client = http_client is None
    try:
        resp = await client.post(
            f"{cfg.base_url}/safety/check",
            json={"text": query_text, "user_id": user_id, "correlation_id": correlation_id},
            timeout=cfg.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        _log.info(
            "safety_check.unreachable",
            correlation_id=correlation_id,
            error=str(exc),
        )
        return
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code == 404:
        _log.info(
            "safety_check.not_deployed",
            correlation_id=correlation_id,
            status=404,
        )
        return

    if resp.status_code >= 500:
        _log.warning(
            "safety_check.server_error",
            correlation_id=correlation_id,
            status=resp.status_code,
        )
        return

    if resp.status_code != 200:
        _log.info(
            "safety_check.unexpected_status",
            correlation_id=correlation_id,
            status=resp.status_code,
        )
        return

    try:
        payload = resp.json()
    except ValueError:
        _log.warning("safety_check.malformed_response", correlation_id=correlation_id)
        return

    if payload.get("flagged") is True:
        category = payload.get("category", "unknown")
        _log.warning(
            "safety_check.flagged",
            correlation_id=correlation_id,
            category=category,
        )
        raise SelfHarmDetectedException(f"Query flagged by safety service: {category}")


__all__ = ["SafetyConfig", "check_query_safety"]
