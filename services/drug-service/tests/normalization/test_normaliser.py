"""Tests for RxNormNormaliser."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.drug_service.exceptions import (
    AmbiguousDrugException,
    DrugNotFoundException,
    RxNormAPIException,
)
from services.drug_service.models.db import RxNormCacheEntry
from services.drug_service.normalization import (
    RxNormNormaliser,
    RxNormProperties,
    normalise_drug_name,
)
from services.drug_service.normalization.rxnorm_api import RxNormAPIClientLike

# ─── Fakes & fixtures ─────────────────────────────────────────────


class FakeRxNormAPI(RxNormAPIClientLike):
    """Configurable fake — set ``names_to_rxcui`` and ``rxcui_to_props``."""

    def __init__(
        self,
        names_to_rxcui: dict[str, str | None] | None = None,
        rxcui_to_props: dict[str, RxNormProperties | None] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self.names_to_rxcui = names_to_rxcui or {}
        self.rxcui_to_props = rxcui_to_props or {}
        self.raise_on = raise_on
        self.find_calls: list[str] = []
        self.props_calls: list[str] = []

    async def find_rxcui_by_name(self, name: str) -> str | None:
        self.find_calls.append(name)
        if self.raise_on == "find":
            raise RxNormAPIException("simulated network failure")
        return self.names_to_rxcui.get(name.lower())

    async def get_properties(self, rxcui: str) -> RxNormProperties | None:
        self.props_calls.append(rxcui)
        if self.raise_on == "properties":
            raise RxNormAPIException("simulated network failure")
        return self.rxcui_to_props.get(rxcui)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        from services.drug_service.models.db import Base

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ─── normalise_drug_name ──────────────────────────────────────────


def test_normalise_lowercases_and_collapses_whitespace() -> None:
    assert normalise_drug_name("  IBUprofen  ") == "ibuprofen"
    assert normalise_drug_name("ace-Tamino Phen") == "ace-tamino phen"


def test_normalise_preserves_hyphen() -> None:
    """Drug names like co-amoxiclav should keep their hyphen."""
    assert normalise_drug_name("Co-Amoxiclav") == "co-amoxiclav"


def test_normalise_strips_trademark_symbols() -> None:
    """™ and ® shouldn't survive normalisation."""
    assert normalise_drug_name("Tylenol®") == "tylenol"


# ─── Tier 1: exact cache hit ──────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_match_returns_cached_entry(session: AsyncSession) -> None:
    session.add(
        RxNormCacheEntry(
            input_name_normalised="ibuprofen",
            input_name_original="Ibuprofen",
            rxcui="5640",
            generic_name="ibuprofen",
            brand_names=["Advil", "Motrin"],
            drug_class="NSAID",
            resolution_path="exact",
            confidence=1.0,
        )
    )
    await session.commit()

    api = FakeRxNormAPI()
    normaliser = RxNormNormaliser(session=session, api_client=api)
    result = await normaliser.resolve("Ibuprofen")

    assert result.rxcui == "5640"
    assert result.generic_name == "ibuprofen"
    assert result.normalisation_path == "exact"
    # No API calls
    assert api.find_calls == []


# ─── Tier 2: fuzzy match ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuzzy_match_resolves_typo(session: AsyncSession) -> None:
    session.add(
        RxNormCacheEntry(
            input_name_normalised="ibuprofen",
            input_name_original="ibuprofen",
            rxcui="5640",
            generic_name="ibuprofen",
            brand_names=["Advil"],
            drug_class="NSAID",
            resolution_path="exact",
            confidence=1.0,
        )
    )
    await session.commit()
    api = FakeRxNormAPI()
    normaliser = RxNormNormaliser(session=session, api_client=api)

    # Typo → should fuzzy-match the cached ibuprofen
    result = await normaliser.resolve("ibuprofin")
    assert result.rxcui == "5640"
    assert result.normalisation_path == "fuzzy"
    # The typo was cached for next time
    typo_row = (
        await session.execute(
            select(RxNormCacheEntry).where(RxNormCacheEntry.input_name_normalised == "ibuprofin")
        )
    ).scalar_one_or_none()
    assert typo_row is not None
    assert typo_row.resolution_path == "fuzzy"


@pytest.mark.asyncio
async def test_fuzzy_threshold_rejects_too_distant(session: AsyncSession) -> None:
    session.add(
        RxNormCacheEntry(
            input_name_normalised="ibuprofen",
            input_name_original="ibuprofen",
            rxcui="5640",
            generic_name="ibuprofen",
            brand_names=[],
            drug_class=None,
            resolution_path="exact",
            confidence=1.0,
        )
    )
    await session.commit()
    # No fuzzy/exact match → must fall to API; API also says no
    api = FakeRxNormAPI(names_to_rxcui={"unrelateddrugname": None})
    normaliser = RxNormNormaliser(session=session, api_client=api)
    with pytest.raises(DrugNotFoundException):
        await normaliser.resolve("unrelateddrugname")


@pytest.mark.asyncio
async def test_fuzzy_ambiguity_raises(session: AsyncSession) -> None:
    """When two cached drugs are equally close, raise rather than guess."""
    for name, rxcui in [("amlodipine", "17767"), ("amoxicillin", "723")]:
        session.add(
            RxNormCacheEntry(
                input_name_normalised=name,
                input_name_original=name,
                rxcui=rxcui,
                generic_name=name,
                brand_names=[],
                drug_class=None,
                resolution_path="exact",
                confidence=1.0,
            )
        )
    await session.commit()
    api = FakeRxNormAPI()
    # Lower threshold so the fuzzy stage actually catches both;
    # wide margin so any score gap counts as ambiguous.
    normaliser = RxNormNormaliser(
        session=session,
        api_client=api,
        fuzzy_threshold=30.0,
        ambiguity_margin=50.0,
    )
    with pytest.raises(AmbiguousDrugException):
        await normaliser.resolve("amo")


# ─── Tier 3: RxNorm API ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_resolves_new_drug_and_caches(session: AsyncSession) -> None:
    api = FakeRxNormAPI(
        names_to_rxcui={"warfarin": "11289"},
        rxcui_to_props={
            "11289": RxNormProperties(
                rxcui="11289",
                generic_name="warfarin",
                brand_names=("Coumadin", "Jantoven"),
                drug_class=None,
            )
        },
    )
    normaliser = RxNormNormaliser(session=session, api_client=api)
    result = await normaliser.resolve("Warfarin")
    assert result.rxcui == "11289"
    assert result.normalisation_path == "rxnorm_api"

    # Cached for next time → second call hits tier 1
    api.find_calls.clear()
    result2 = await normaliser.resolve("Warfarin")
    assert result2.rxcui == "11289"
    assert result2.normalisation_path == "exact"
    assert api.find_calls == []  # tier 1 hit, no API call


@pytest.mark.asyncio
async def test_api_unreachable_drug_raises_not_found(session: AsyncSession) -> None:
    api = FakeRxNormAPI(names_to_rxcui={"not-a-real-drug": None})
    normaliser = RxNormNormaliser(session=session, api_client=api)
    with pytest.raises(DrugNotFoundException):
        await normaliser.resolve("not-a-real-drug")


@pytest.mark.asyncio
async def test_api_network_error_surfaces(session: AsyncSession) -> None:
    api = FakeRxNormAPI(raise_on="find")
    normaliser = RxNormNormaliser(session=session, api_client=api)
    with pytest.raises(RxNormAPIException):
        await normaliser.resolve("metformin")


@pytest.mark.asyncio
async def test_api_returns_rxcui_but_no_properties(session: AsyncSession) -> None:
    api = FakeRxNormAPI(
        names_to_rxcui={"orphan": "999999"},
        rxcui_to_props={"999999": None},
    )
    normaliser = RxNormNormaliser(session=session, api_client=api)
    with pytest.raises(DrugNotFoundException):
        await normaliser.resolve("Orphan")


# ─── Edge cases ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_name_raises(session: AsyncSession) -> None:
    api = FakeRxNormAPI()
    normaliser = RxNormNormaliser(session=session, api_client=api)
    with pytest.raises(DrugNotFoundException):
        await normaliser.resolve("   ")


@pytest.mark.asyncio
async def test_same_drug_different_cases_share_cache_entry(session: AsyncSession) -> None:
    api = FakeRxNormAPI(
        names_to_rxcui={"aspirin": "1191"},
        rxcui_to_props={
            "1191": RxNormProperties(
                rxcui="1191",
                generic_name="aspirin",
                brand_names=("Bayer",),
                drug_class=None,
            )
        },
    )
    normaliser = RxNormNormaliser(session=session, api_client=api)
    a = await normaliser.resolve("ASPIRIN")
    b = await normaliser.resolve("aspirin")
    c = await normaliser.resolve("  Aspirin  ")
    assert a.rxcui == b.rxcui == c.rxcui == "1191"
    # Only ONE call to the API across all three
    assert len(api.find_calls) == 1
