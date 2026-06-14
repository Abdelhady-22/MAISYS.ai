"""Three-tier drug-name resolution: exact → fuzzy → RxNorm API.

Resolution sequence::

    name → normalise (lowercase, collapse whitespace, strip punctuation)
         ↓
    1. Exact match: SELECT FROM rxnorm_cache WHERE input_name_normalised = :n
    2. Fuzzy match: rapidfuzz token-set ratio ≥ 0.85 against the cache
    3. RxNorm API: GET rxcui.json + properties.json + related (BN)

Hits at tier 2 or 3 are written back to the cache so future calls
short-circuit at tier 1. The ``resolution_path`` column on the
cache row records which tier produced the entry.

The fuzzy step is O(n) over cache rows. For the early phase
(< 10K cached drugs) this is fine. Once the cache reaches the
hundreds of thousands, swap the candidate-retrieval step for a
Postgres trigram index (pg_trgm) — the public API of this class
will not change.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.drug_service.exceptions import (
    AmbiguousDrugException,
    DrugNotFoundException,
    RxNormAPIException,
)
from services.drug_service.models.db import RxNormCacheEntry
from services.drug_service.models.schemas import NormalisedDrug
from services.drug_service.normalization.rxnorm_api import RxNormAPIClientLike
from shared.logger import get_logger

_log = get_logger(__name__)

DEFAULT_FUZZY_THRESHOLD = 85.0  # rapidfuzz scores 0-100; 85 ≈ Levenshtein ratio 0.85
DEFAULT_FUZZY_TOP_K = 5
DEFAULT_AMBIGUITY_MARGIN = 3.0  # if top-2 scores are within this, raise Ambiguous


def normalise_drug_name(name: str) -> str:
    """Canonicalise an input drug name for cache lookups.

    Lower-cases, collapses whitespace, and strips characters that are
    not letters, digits, or hyphens (drug names like "co-amoxiclav"
    retain the hyphen; trade-mark symbols are dropped). Two callers
    who type the same drug with slightly different formatting end up
    on the same cache row.
    """
    lowered = name.strip().lower()
    cleaned = re.sub(r"[^\w\s-]", " ", lowered, flags=re.UNICODE)
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    return collapsed


class RxNormNormaliser:
    """Resolves a drug-name input to a canonical RxCUI + metadata."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        api_client: RxNormAPIClientLike,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
        fuzzy_top_k: int = DEFAULT_FUZZY_TOP_K,
        ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
    ) -> None:
        self._session = session
        self._api = api_client
        self._threshold = fuzzy_threshold
        self._top_k = fuzzy_top_k
        self._margin = ambiguity_margin

    async def resolve(self, name: str) -> NormalisedDrug:
        """Resolve ``name`` through the three tiers.

        Raises:
            DrugNotFoundException: no tier produced a match.
            AmbiguousDrugException: fuzzy returned 2+ matches within
                ``ambiguity_margin`` of each other — caller must
                disambiguate before retrying.
            RxNormAPIException: tier 3 (API) errored out AND tiers 1/2
                produced nothing.
        """
        normalised = normalise_drug_name(name)
        if not normalised:
            raise DrugNotFoundException(f"Empty or unrecognisable drug name: {name!r}")

        # Tier 1: exact cache hit
        exact = await self._exact_match(normalised)
        if exact is not None:
            _log.info("rxnorm.resolve.exact", input=name, rxcui=exact.rxcui)
            return _entry_to_normalised(exact, path_override="exact")

        # Tier 2: fuzzy against the existing cache
        fuzzy = await self._fuzzy_match(normalised)
        if fuzzy is not None:
            _log.info(
                "rxnorm.resolve.fuzzy",
                input=name,
                matched_to=fuzzy.input_name_normalised,
                rxcui=fuzzy.rxcui,
            )
            # Persist the new spelling so future identical typos hit tier 1
            await self._upsert_alias(
                normalised_input=normalised,
                original_input=name,
                source_entry=fuzzy,
                resolution_path="fuzzy",
                confidence_override=None,
            )
            return _entry_to_normalised(fuzzy, path_override="fuzzy")

        # Tier 3: RxNorm API
        return await self._resolve_via_api(name, normalised)

    async def _exact_match(self, normalised: str) -> RxNormCacheEntry | None:
        result = await self._session.execute(
            select(RxNormCacheEntry).where(RxNormCacheEntry.input_name_normalised == normalised)
        )
        return result.scalar_one_or_none()

    async def _fuzzy_match(self, normalised: str) -> RxNormCacheEntry | None:
        all_entries = (await self._session.execute(select(RxNormCacheEntry))).scalars().all()
        if not all_entries:
            return None

        # rapidfuzz scores against the dict VALUES, not keys — so we
        # pass a list of normalised-name strings and look up the entry
        # by name afterwards.
        by_name = {e.input_name_normalised: e for e in all_entries}
        candidates = process.extract(
            normalised,
            list(by_name.keys()),
            scorer=fuzz.token_set_ratio,
            limit=self._top_k,
        )
        # rapidfuzz returns (matched_string, score, index) for list input
        scored: list[tuple[float, RxNormCacheEntry]] = []
        for matched_name, score, _ in candidates:
            if score >= self._threshold:
                scored.append((score, by_name[matched_name]))
        if not scored:
            return None

        # If two top candidates are close, the result is ambiguous —
        # raise so the caller can ask the user to disambiguate
        if len(scored) >= 2 and (scored[0][0] - scored[1][0]) < self._margin:
            top_names = ", ".join(e.generic_name for _, e in scored[:3])
            raise AmbiguousDrugException(f"Multiple close matches for {normalised!r}: {top_names}")

        return scored[0][1]

    async def _resolve_via_api(self, original: str, normalised: str) -> NormalisedDrug:
        try:
            rxcui = await self._api.find_rxcui_by_name(original)
        except RxNormAPIException:
            raise
        if rxcui is None:
            raise DrugNotFoundException(f"RxNorm returned no match for {original!r}")
        properties = await self._api.get_properties(rxcui)
        if properties is None:
            raise DrugNotFoundException(f"RxNorm has rxcui={rxcui} but no properties")

        entry = RxNormCacheEntry(
            input_name_normalised=normalised,
            input_name_original=original,
            rxcui=properties.rxcui,
            generic_name=properties.generic_name,
            brand_names=list(properties.brand_names),
            drug_class=properties.drug_class,
            resolution_path="rxnorm_api",
            confidence=1.0,
        )
        self._session.add(entry)
        await self._session.commit()
        _log.info("rxnorm.resolve.api", input=original, rxcui=properties.rxcui)
        return _entry_to_normalised(entry)

    async def _upsert_alias(
        self,
        *,
        normalised_input: str,
        original_input: str,
        source_entry: RxNormCacheEntry,
        resolution_path: str,
        confidence_override: float | None,
    ) -> None:
        """Persist a new spelling that matched an existing RxCUI."""
        existing = await self._exact_match(normalised_input)
        if existing is not None:
            return  # race: another request beat us to it
        self._session.add(
            RxNormCacheEntry(
                input_name_normalised=normalised_input,
                input_name_original=original_input,
                rxcui=source_entry.rxcui,
                generic_name=source_entry.generic_name,
                brand_names=list(source_entry.brand_names),
                drug_class=source_entry.drug_class,
                resolution_path=resolution_path,
                confidence=confidence_override if confidence_override is not None else 0.9,
            )
        )
        await self._session.commit()


def _entry_to_normalised(
    entry: RxNormCacheEntry,
    *,
    path_override: str | None = None,
) -> NormalisedDrug:
    return NormalisedDrug(
        rxcui=entry.rxcui,
        generic_name=entry.generic_name,
        brand_names=list(entry.brand_names),
        drug_class=entry.drug_class,
        confidence=entry.confidence,
        normalisation_path=(path_override or entry.resolution_path),  # type: ignore[arg-type]
    )


__all__ = ["RxNormNormaliser", "normalise_drug_name"]
