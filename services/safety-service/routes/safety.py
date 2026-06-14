"""``/safety/check`` and ``/safety/wrap`` HTTP routes.

Routes are intentionally thin — they:

1. Validate input (Pydantic does the structural part)
2. Pull the relevant injected service from ``app.state``
3. Call exactly one service method
4. Wrap the result in the shared ``APIResponse`` envelope

Authentication: every endpoint requires a valid JWT via
``Depends(get_current_user)``. The brief permits service-to-service
calls without auth in some deployments — for Phase 3 we keep
authentication on by default and document that the gateway is
responsible for not forwarding unauthenticated traffic.

Both endpoints are POST because they accept bodies. ``/safety/check``
in particular is *not* idempotent in the cache sense — calling it
twice with the same input is fine and returns the same verdict, but
we don't want the verdict cached by a CDN, so POST is also
operationally safer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from services.safety_service.models.schemas import (
    SafetyCheckRequest,
    SafetyCheckResponse,
    SafetyWrapRequest,
    SafetyWrapResponse,
)
from services.safety_service.services.disclaimer_injector import DisclaimerInjector
from services.safety_service.services.emergency_detector import EmergencyDetector
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse
from shared.logger import get_logger

_log = get_logger(__name__)
router = APIRouter(prefix="/safety", tags=["safety"])


def _get_detector(request: Request) -> EmergencyDetector:
    detector: EmergencyDetector | None = getattr(request.app.state, "emergency_detector", None)
    if detector is None:  # pragma: no cover — wiring guarantees this
        raise RuntimeError("emergency_detector is not wired into app.state")
    return detector


def _get_injector(request: Request) -> DisclaimerInjector:
    injector: DisclaimerInjector | None = getattr(request.app.state, "disclaimer_injector", None)
    if injector is None:  # pragma: no cover — wiring guarantees this
        raise RuntimeError("disclaimer_injector is not wired into app.state")
    return injector


@router.post(
    "/check",
    response_model=APIResponse[SafetyCheckResponse],
    summary="Detect medical emergency indicators in free text",
)
async def safety_check(
    body: SafetyCheckRequest,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),
) -> JSONResponse:
    detector = _get_detector(http_request)
    verdict = await detector.detect(body.text)
    _log.info(
        "safety.check.completed",
        user_id=user.sub,
        session_id=body.session_id,
        language=body.language,
        is_emergency=verdict.is_emergency,
        category=verdict.category,
        stage=verdict.stage,
    )
    response = SafetyCheckResponse(
        is_emergency=verdict.is_emergency,
        severity=verdict.severity,
        detected_pattern=verdict.detected_pattern,
        category=verdict.category,
        detection_stage=verdict.stage,
        emergency_response=verdict.emergency_response,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=APIResponse[SafetyCheckResponse].ok(response).model_dump(mode="json"),
    )


@router.post(
    "/wrap",
    response_model=APIResponse[SafetyWrapResponse],
    summary="Wrap a service response with profile warnings and disclaimer",
)
async def safety_wrap(
    body: SafetyWrapRequest,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),
) -> JSONResponse:
    injector = _get_injector(http_request)
    response = injector.wrap(body)
    _log.info(
        "safety.wrap.completed",
        user_id=user.sub,
        language=body.language,
        context=body.context,
        warnings_count=len(response.profile_warnings),
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=APIResponse[SafetyWrapResponse].ok(response).model_dump(mode="json"),
    )
