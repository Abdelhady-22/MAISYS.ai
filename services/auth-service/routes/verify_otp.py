"""POST /auth/verify-otp — dispatches by ``purpose``."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import (
    OTPExpiredException,
    OTPInvalidException,
    OTPMaxAttemptsException,
)
from models.schemas import (
    LoginResponse,
    UserPublic,
    VerifyOTPRequest,
    VerifyOTPResponse,
)
from repository import OTPRepository
from services.login_service import LoginService
from services.registration_service import RegistrationService
from shared.auth import Role
from shared.error_handler import APIResponse
from shared.models import get_db_session
from utils.otp import verify_otp

router = APIRouter(tags=["auth"])


def _purpose_response_for_email_verify(
    body: VerifyOTPRequest,
) -> APIResponse[Any]:
    return APIResponse[VerifyOTPResponse].ok(
        VerifyOTPResponse(verified=True, message="Email verified successfully.")
    )


@router.post(
    "/auth/verify-otp",
    response_model=APIResponse[VerifyOTPResponse | LoginResponse],
)
async def verify_otp_endpoint(
    body: VerifyOTPRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[Any]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if body.purpose == "email_verify":
        service = RegistrationService(db)
        await service.verify_email(
            user_id=body.user_id,
            code=body.code,
            ip_address=ip,
            user_agent=ua,
        )
        return _purpose_response_for_email_verify(body)

    if body.purpose == "login_otp":
        # Inline the OTP check here rather than adding a method to
        # LoginService that just calls increment_attempt — we already
        # have the repo dependencies handy and the path is short.
        max_attempts = int(os.environ.get("OTP_MAX_ATTEMPTS", "3"))
        otps = OTPRepository(db)
        active = await otps.get_active(body.user_id, purpose="login_otp")
        if active is None:
            raise OTPExpiredException("No active login code; please log in again")
        expires_at = active.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise OTPExpiredException("Login code has expired")

        if not verify_otp(body.code, active.code_hash):
            new_attempts = await otps.increment_attempt(active.id)
            if new_attempts >= max_attempts:
                await otps.invalidate(active.id)
                await db.commit()
                raise OTPMaxAttemptsException("Too many failed attempts; please log in again")
            await db.commit()
            raise OTPInvalidException("Code does not match")

        await otps.mark_used(active.id)
        await db.commit()

        login = LoginService(db)
        result = await login.complete_otp_login(user_id=body.user_id, ip_address=ip, user_agent=ua)
        return APIResponse[LoginResponse].ok(
            LoginResponse(
                access_token=result.access_token,
                refresh_token=result.refresh_token,
                expires_in=result.expires_in,
                user=UserPublic(
                    id=result.user.id,
                    email=result.user.email,
                    role=Role(result.user.role),
                    email_verified=result.user.email_verified,
                    language_preference=result.user.language_preference,
                ),
            )
        )

    if body.purpose == "password_reset":
        # password_reset uses its own confirm endpoint
        # (POST /auth/password/reset/confirm), not /verify-otp.
        raise OTPInvalidException(
            "purpose=password_reset is handled at /auth/password/reset/confirm"
        )

    raise OTPInvalidException(f"Unknown purpose: {body.purpose}")
