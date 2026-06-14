"""``/translate`` and ``/translate/batch`` routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from services.translation_service.models.schemas import (
    BatchTranslateRequest,
    BatchTranslateResponse,
    TranslateRequest,
    TranslateResponse,
)
from services.translation_service.services.translation_service import (
    TranslationService,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse

router = APIRouter(prefix="/translate", tags=["translation"])


def _get_service(request: Request) -> TranslationService:
    svc: TranslationService | None = getattr(request.app.state, "translation_service", None)
    if svc is None:
        raise RuntimeError("translation_service is not wired into app.state")
    return svc


@router.post(
    "",
    response_model=APIResponse[TranslateResponse],
    summary="Translate a single text between Arabic and English",
)
async def translate(
    body: TranslateRequest,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),  # noqa: ARG001
) -> JSONResponse:
    svc = _get_service(http_request)
    response = await svc.translate(body)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=APIResponse[TranslateResponse].ok(response).model_dump(mode="json"),
    )


@router.post(
    "/batch",
    response_model=APIResponse[BatchTranslateResponse],
    summary="Translate up to 50 texts concurrently; partial failures don't abort",
)
async def translate_batch(
    body: BatchTranslateRequest,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),  # noqa: ARG001
) -> JSONResponse:
    svc = _get_service(http_request)
    response = await svc.translate_batch(body)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=APIResponse[BatchTranslateResponse].ok(response).model_dump(mode="json"),
    )
