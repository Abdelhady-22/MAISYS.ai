"""Integration tests for ``/safety/check`` and ``/safety/wrap`` routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


# ─── /safety/check ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_emergency_returns_full_payload(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/check",
        json={"text": "I have chest pain and difficulty breathing", "language": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["is_emergency"] is True
    assert data["category"] == "cardiac"
    assert data["detection_stage"] == "stage_1"
    er = data["emergency_response"]
    assert er["do_not_wait"] is True
    assert er["session_should_halt"] is True
    assert len(er["actions_en"]) > 0
    assert len(er["actions_ar"]) > 0


@pytest.mark.asyncio
async def test_check_safe_input_returns_minimal_payload(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/check",
        json={"text": "What is the recommended dose of vitamin D?", "language": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["is_emergency"] is False
    assert data["emergency_response"] is None
    assert data["category"] is None


@pytest.mark.asyncio
async def test_check_arabic_emergency(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/check",
        json={"text": "أعتقد عندي سكتة دماغية", "language": "ar"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_emergency"] is True
    assert data["category"] == "stroke"


@pytest.mark.asyncio
async def test_check_session_id_propagates_in_logs(client: AsyncClient) -> None:
    """Smoke test — session_id is accepted and doesn't break the response.
    We don't assert on log capture here; just that the field is allowed."""
    response = await client.post(
        "/safety/check",
        json={
            "text": "I'm suicidal",
            "language": "en",
            "session_id": "sess-abc-123",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["category"] == "mental_health_crisis"


@pytest.mark.asyncio
async def test_check_empty_text_rejected_by_pydantic(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/check",
        json={"text": "", "language": "en"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_check_oversized_text_rejected_by_pydantic(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/check",
        json={"text": "x" * 5000, "language": "en"},
    )
    assert response.status_code == 422


# ─── /safety/wrap ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrap_basic_includes_disclaimer(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/wrap",
        json={
            "response_content": "Drug information.",
            "language": "en",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["wrapped_content"] == "Drug information."
    assert data["disclaimer_en"]
    assert data["disclaimer_ar"]
    assert data["profile_warnings"] == []


@pytest.mark.asyncio
async def test_wrap_pregnant_user_with_ibuprofen_warns(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/wrap",
        json={
            "response_content": "Ibuprofen reduces inflammation.",
            "language": "en",
            "user_profile": {"is_pregnant": True},
            "context": "drug_profile",
            "drug_names": ["ibuprofen"],
        },
    )
    assert response.status_code == 200
    warnings = response.json()["data"]["profile_warnings"]
    assert len(warnings) == 1
    assert warnings[0]["drug"] == "ibuprofen"
    assert warnings[0]["type"] == "pregnancy_warning"
    assert warnings[0]["severity"] == "high"


@pytest.mark.asyncio
async def test_wrap_invalid_profile_returns_400(client: AsyncClient) -> None:
    response = await client.post(
        "/safety/wrap",
        json={
            "response_content": "...",
            "language": "en",
            "user_profile": {"is_pregnant": False, "pregnancy_trimester": 2},
            "context": "generic",
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_SAFETY_INPUT"


@pytest.mark.asyncio
async def test_wrap_extra_field_rejected(client: AsyncClient) -> None:
    """Pydantic ``extra='forbid'`` should reject unknown fields."""
    response = await client.post(
        "/safety/wrap",
        json={
            "response_content": "...",
            "language": "en",
            "unknown_field": "should_be_rejected",
        },
    )
    assert response.status_code == 422
