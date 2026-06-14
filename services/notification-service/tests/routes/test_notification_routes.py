"""Integration tests for /notifications routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_with_db_wired(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


# ─── POST /notifications/send ─────────────────────────────────────


def _good_body() -> dict[str, object]:
    return {
        "notification_type": "email_verify",
        "user_id": "user-1",
        "recipient_email": "ahmad@example.com",
        "language": "en",
        "template_name": "email_verify",
        "template_vars": {
            "user_name": "Ahmad",
            "otp_code": "847291",
            "expires_in_minutes": 10,
        },
        "correlation_id": "corr-1",
        "priority": "high",
    }


@pytest.mark.asyncio
async def test_send_returns_202_with_notification_id(client: AsyncClient) -> None:
    response = await client.post("/notifications/send", json=_good_body())
    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert "notification_id" in data
    assert len(data["notification_id"]) == 32  # UUID4 hex
    assert data["status"] in {"queued", "delivering", "delivered"}
    assert "accepted_at" in data


@pytest.mark.asyncio
async def test_send_with_missing_required_field_422(client: AsyncClient) -> None:
    bad = _good_body()
    del bad["recipient_email"]
    response = await client.post("/notifications/send", json=bad)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_send_with_invalid_email_422(client: AsyncClient) -> None:
    bad = _good_body()
    bad["recipient_email"] = "not-an-email"
    response = await client.post("/notifications/send", json=bad)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_send_with_extra_field_422(client: AsyncClient) -> None:
    """Pydantic ``extra='forbid'`` rejects unknown fields."""
    bad = _good_body()
    bad["unexpected"] = "field"
    response = await client.post("/notifications/send", json=bad)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_send_with_template_name_mismatch_400(client: AsyncClient) -> None:
    bad = _good_body()
    bad["template_name"] = "password_reset"  # mismatch
    response = await client.post("/notifications/send", json=bad)
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "TEMPLATE_NAME_MISMATCH"


@pytest.mark.asyncio
async def test_send_with_unknown_notification_type_422(client: AsyncClient) -> None:
    bad = _good_body()
    bad["notification_type"] = "made_up_type"
    bad["template_name"] = "made_up_type"
    response = await client.post("/notifications/send", json=bad)
    assert response.status_code == 422


# ─── GET /notifications/{id} ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_notification_after_send(client: AsyncClient) -> None:
    send_response = await client.post("/notifications/send", json=_good_body())
    notification_id = send_response.json()["data"]["notification_id"]

    # Give the background task a moment to mark delivered.
    # (FakeEmailAdapter is in-memory so this is nearly instant.)
    import asyncio

    for _ in range(20):
        get_response = await client.get(f"/notifications/{notification_id}")
        assert get_response.status_code == 200
        if get_response.json()["data"]["status"] == "delivered":
            break
        await asyncio.sleep(0.01)

    data = get_response.json()["data"]
    assert data["notification_id"] == notification_id
    assert data["notification_type"] == "email_verify"
    assert data["user_id"] == "user-1"
    assert data["recipient_email"] == "ahmad@example.com"
    assert data["language"] == "en"
    assert data["status"] == "delivered"
    assert data["attempts"] >= 1
    assert data["delivered_at"] is not None
    assert data["last_error"] is None


@pytest.mark.asyncio
async def test_get_unknown_notification_404(client: AsyncClient) -> None:
    response = await client.get("/notifications/00000000000000000000000000000000")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOTIFICATION_NOT_FOUND"


# ─── Arabic happy path through HTTP ───────────────────────────────


@pytest.mark.asyncio
async def test_send_arabic_login_otp(client: AsyncClient) -> None:
    body = {
        "notification_type": "login_otp",
        "user_id": "user-2",
        "recipient_email": "sara@example.com",
        "language": "ar",
        "template_name": "login_otp",
        "template_vars": {"otp_code": "999000", "expires_in_minutes": 5},
        "priority": "high",
    }
    response = await client.post("/notifications/send", json=body)
    assert response.status_code == 202
    notification_id = response.json()["data"]["notification_id"]

    import asyncio

    for _ in range(20):
        get_resp = await client.get(f"/notifications/{notification_id}")
        if get_resp.json()["data"]["status"] == "delivered":
            break
        await asyncio.sleep(0.01)
    assert get_resp.json()["data"]["status"] == "delivered"
    assert get_resp.json()["data"]["language"] == "ar"
