"""Tests for the drug-service skeleton.

Verifies:

* /healthz returns 200 with status=ok
* /readyz returns 200 and reports postgres=ok via the test DB override
* The OpenAPI schema enumerates every agent endpoint at the right path
* Every agent endpoint returns 501 NOT_IMPLEMENTED today (will flip
  to 200 as each agent commit lands)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_reports_postgres_ok(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["checks"]["postgres"] == "ok"


@pytest.mark.asyncio
async def test_openapi_lists_every_agent_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    expected_paths = {
        "/drugs/lookup",
        "/drugs/interactions",
        "/drugs/dosage",
        "/drugs/compare",
        "/drugs/pharmacokinetics",
        "/drugs/alternatives",
        "/drugs/acquisition",
        "/drugs/query",
        "/healthz",
        "/readyz",
    }
    actual_paths = set(spec["paths"].keys())
    assert expected_paths.issubset(actual_paths)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,payload",
    [
        ("/drugs/lookup", {"drug": {"name": "ibuprofen"}, "language": "en"}),
        (
            "/drugs/interactions",
            {"drugs": [{"name": "ibuprofen"}, {"name": "warfarin"}], "language": "en"},
        ),
        ("/drugs/dosage", {"drug": {"name": "metformin"}, "language": "en"}),
        (
            "/drugs/compare",
            {"drugs": [{"name": "amoxicillin"}, {"name": "azithromycin"}], "language": "en"},
        ),
        ("/drugs/pharmacokinetics", {"drug": {"name": "atorvastatin"}, "language": "en"}),
        (
            "/drugs/alternatives",
            {"drug": {"name": "lisinopril"}, "reason": "cough", "language": "en"},
        ),
        (
            "/drugs/acquisition",
            {"drug": {"name": "metformin"}, "country_iso": "EG", "language": "en"},
        ),
        ("/drugs/query", {"text": "what is ibuprofen", "language": "en"}),
    ],
)
async def test_agent_endpoints_return_501_stub(
    client: AsyncClient, path: str, payload: dict
) -> None:
    """Every agent endpoint is a stub until its commit lands."""
    resp = await client.post(path, json=payload)
    assert resp.status_code == 501, f"{path} returned {resp.status_code}, expected 501"
    body = resp.json()
    detail = body.get("detail", {})
    assert detail.get("code") == "AGENT_NOT_IMPLEMENTED"


@pytest.mark.asyncio
async def test_request_validation_rejects_malformed_payload(client: AsyncClient) -> None:
    """Pydantic validation runs before the 501 stub — request shape is enforced."""
    # Missing required `drug` field
    resp = await client.post("/drugs/lookup", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_interactions_requires_at_least_two_drugs(client: AsyncClient) -> None:
    """Schema constraint: drugs list min_length=2."""
    resp = await client.post(
        "/drugs/interactions", json={"drugs": [{"name": "ibuprofen"}], "language": "en"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_acquisition_requires_iso_country_code(client: AsyncClient) -> None:
    """country_iso is exactly 2 characters."""
    resp = await client.post(
        "/drugs/acquisition",
        json={"drug": {"name": "metformin"}, "country_iso": "EGY", "language": "en"},
    )
    assert resp.status_code == 422
