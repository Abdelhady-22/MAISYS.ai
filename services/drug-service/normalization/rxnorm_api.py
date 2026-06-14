"""Async client for the public RxNorm REST API.

Endpoint reference: https://rxnav.nlm.nih.gov/RxNormAPIs.html

This client exposes the two endpoints we need:

* ``find_rxcui_by_name(name)`` — best-match RxCUI for a drug name.
* ``get_properties(rxcui)`` — generic name, brand names, and the
  drug class (from RxClass) for a known RxCUI.

The client raises ``RxNormAPIException`` on network failure or
non-2xx responses. It does NOT cache — caching lives one layer up
in ``RxNormNormaliser`` (so the Postgres cache is the single source
of truth and survives process restarts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from services.drug_service.exceptions import RxNormAPIException
from shared.logger import get_logger

_log = get_logger(__name__)

RXNORM_API_BASE = "https://rxnav.nlm.nih.gov/REST"
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class RxNormProperties:
    rxcui: str
    generic_name: str
    brand_names: tuple[str, ...]
    drug_class: str | None


class RxNormAPIClientLike:
    """Protocol surface — what RxNormNormaliser depends on.

    The real client below implements this; tests inject a fake.
    """

    async def find_rxcui_by_name(self, name: str) -> str | None:
        raise NotImplementedError

    async def get_properties(self, rxcui: str) -> RxNormProperties | None:
        raise NotImplementedError


class RxNormAPIClient(RxNormAPIClientLike):
    """Production HTTP client."""

    def __init__(
        self,
        *,
        base_url: str = RXNORM_API_BASE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._owned_client: httpx.AsyncClient | None = None
        if http_client is None:
            self._owned_client = httpx.AsyncClient(timeout=timeout_seconds)
            self._client = self._owned_client
        else:
            self._client = http_client

    async def close(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()

    async def find_rxcui_by_name(self, name: str) -> str | None:
        """GET /rxcui.json?name=<name> → first RxCUI in idGroup, or None."""
        url = f"{self._base_url}/rxcui.json"
        try:
            resp = await self._client.get(url, params={"name": name})
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        except httpx.HTTPError as exc:
            _log.warning("rxnorm.find_rxcui.http_error", name=name, error=str(exc))
            raise RxNormAPIException(f"RxNorm find_rxcui failed: {exc}") from exc

        id_group = payload.get("idGroup", {})
        ids = id_group.get("rxnormId") or []
        if not ids:
            return None
        return str(ids[0])

    async def get_properties(self, rxcui: str) -> RxNormProperties | None:
        """Compose a properties response from two RxNorm endpoints.

        * ``/rxcui/{cui}/properties.json`` — generic name + tty + …
        * ``/rxcui/{cui}/related.json?tty=BN`` — brand names

        Drug class is left ``None`` here; the RxClass API is separate
        and is queried by ``RxNormNormaliser`` when needed.
        """
        try:
            base_resp = await self._client.get(f"{self._base_url}/rxcui/{rxcui}/properties.json")
            base_resp.raise_for_status()
            base = base_resp.json()
        except httpx.HTTPError as exc:
            _log.warning("rxnorm.properties.http_error", rxcui=rxcui, error=str(exc))
            raise RxNormAPIException(f"RxNorm properties failed: {exc}") from exc

        properties = base.get("properties") or {}
        generic_name = properties.get("name")
        if not generic_name:
            return None

        # Brand names — best-effort; failure here doesn't fail the lookup
        brand_names: tuple[str, ...] = ()
        try:
            brand_resp = await self._client.get(
                f"{self._base_url}/rxcui/{rxcui}/related.json", params={"tty": "BN"}
            )
            brand_resp.raise_for_status()
            brand_payload = brand_resp.json()
            concept_group = (brand_payload.get("relatedGroup") or {}).get("conceptGroup") or []
            names: list[str] = []
            for group in concept_group:
                for prop in group.get("conceptProperties") or []:
                    if prop.get("name"):
                        names.append(prop["name"])
            brand_names = tuple(names)
        except httpx.HTTPError as exc:
            _log.info("rxnorm.brand.lookup_skipped", rxcui=rxcui, error=str(exc))

        return RxNormProperties(
            rxcui=rxcui,
            generic_name=generic_name,
            brand_names=brand_names,
            drug_class=None,
        )


__all__ = ["RxNormAPIClient", "RxNormAPIClientLike", "RxNormProperties"]
