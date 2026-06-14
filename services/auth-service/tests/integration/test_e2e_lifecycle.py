"""End-to-end lifecycle test.

Walks a user through register → verify-otp → login → me → patch-me →
refresh → sessions → logout, exercising the FULL production wiring:

* The real ``main.app`` (CORS, request logging, exception handlers,
  Prometheus, all 12 endpoints).
* The real Pydantic validation.
* The real APIResponse envelope translation.
* The real DB layer (against the in-memory test SQLite, but with the
  same SQLAlchemy session machinery production uses).

This catches integration bugs that unit tests miss — router wiring,
middleware order, exception-handler registration, response-model
serialisation, env-var contracts.
"""

from __future__ import annotations


import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from repository import OTPRepository
from utils.otp import hash_otp


@pytest.mark.asyncio
async def test_full_user_lifecycle(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """One user goes through the full lifecycle: register → use → logout."""

    # ── 1. Register ──────────────────────────────────────────────
    response = await integration_client.post(
        "/auth/register",
        json={
            "email": "e2e@example.com",
            "password": "TestP@ssw0rd1",
            "language_preference": "en",
        },
    )
    assert response.status_code == 201, response.text
    register_body = response.json()
    assert register_body["success"] is True
    user_id = register_body["data"]["user_id"]
    assert register_body["data"]["email"] == "e2e@example.com"

    # ── 2. Fetch the OTP from the DB (in production, email delivers it) ──
    #     The email-service is a stub in Session B, so we read the
    #     active OTP straight from the repository.
    from uuid import UUID

    otps = OTPRepository(db_session)
    active = await otps.get_active(UUID(user_id), purpose="email_verify")
    assert active is not None
    # Re-create a fresh OTP we KNOW the hash of, because the original
    # plaintext code was only ever in the logger stub.
    code = "123456"
    active.code_hash = hash_otp(code)
    await db_session.commit()

    # ── 3. Verify OTP ────────────────────────────────────────────
    response = await integration_client.post(
        "/auth/verify-otp",
        json={"user_id": user_id, "code": code, "purpose": "email_verify"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["verified"] is True

    # ── 4. Login ─────────────────────────────────────────────────
    response = await integration_client.post(
        "/auth/login",
        json={"email": "e2e@example.com", "password": "TestP@ssw0rd1"},
    )
    assert response.status_code == 200, response.text
    login_body = response.json()
    access_token = login_body["data"]["access_token"]
    refresh_token = login_body["data"]["refresh_token"]
    assert login_body["data"]["user"]["email"] == "e2e@example.com"
    auth = {"Authorization": f"Bearer {access_token}"}

    # ── 5. GET /me ───────────────────────────────────────────────
    response = await integration_client.get("/auth/me", headers=auth)
    assert response.status_code == 200, response.text
    me_body = response.json()
    assert me_body["data"]["email"] == "e2e@example.com"
    assert me_body["data"]["email_verified"] is True

    # ── 6. PATCH /me ─────────────────────────────────────────────
    response = await integration_client.patch(
        "/auth/me", json={"display_name": "E2E Tester"}, headers=auth
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["user"]["display_name"] == "E2E Tester"

    # ── 7. Refresh ───────────────────────────────────────────────
    response = await integration_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200, response.text
    refresh_body = response.json()
    new_access = refresh_body["data"]["access_token"]
    new_refresh = refresh_body["data"]["refresh_token"]
    assert new_refresh != refresh_token  # rotated
    auth = {"Authorization": f"Bearer {new_access}"}

    # ── 8. GET /sessions ─────────────────────────────────────────
    response = await integration_client.get("/auth/sessions", headers=auth)
    assert response.status_code == 200, response.text
    sessions_body = response.json()
    # After refresh: 1 active session (old one was rotated, replaced)
    assert len(sessions_body["data"]["sessions"]) == 1

    # ── 9. Logout ────────────────────────────────────────────────
    response = await integration_client.post("/auth/logout", headers=auth)
    assert response.status_code == 200, response.text

    # ── 10. Confirm post-logout access fails ─────────────────────
    #      The JTI is now revoked. /me still PASSES JWT validation
    #      (signature is valid) but the session row is revoked.
    #      Refresh with the now-revoked token must fail.
    response = await integration_client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(
    integration_client: AsyncClient,
) -> None:
    response = await integration_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_endpoint_returns_ready(
    integration_client: AsyncClient,
) -> None:
    response = await integration_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_metrics_endpoint_exposed(integration_client: AsyncClient) -> None:
    """Prometheus instrumentator should mount /metrics."""
    response = await integration_client.get("/metrics")
    assert response.status_code == 200
    # Standard Prometheus exposition format starts with HELP/TYPE lines
    assert b"# HELP" in response.content or b"# TYPE" in response.content


@pytest.mark.asyncio
async def test_unknown_route_returns_404(integration_client: AsyncClient) -> None:
    response = await integration_client.get("/no/such/route")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invalid_request_body_returns_422(
    integration_client: AsyncClient,
) -> None:
    response = await integration_client.post(
        "/auth/register", json={"email": "not-an-email"}  # missing password
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_password_reset_request_silent_for_unknown_email(
    integration_client: AsyncClient,
) -> None:
    """End-to-end: enumeration protection works through the full stack."""
    response = await integration_client.post(
        "/auth/password/reset/request",
        json={"email": "ghost@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
