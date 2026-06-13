"""FastAPI integration for MAISYS exception handling.

Call `setup_exception_handlers(app)` once during application startup.
This registers two handlers:

1. A handler for MaisysException — converts to APIResponse JSON envelope with
   the exception's status_code; logs at WARNING for 4xx and ERROR for 5xx;
   propagates correlation_id from request.state.request_id if not already
   set on the exception.

2. A fallback handler for unhandled Exception — wraps in a generic 500
   APIResponse with code "INTERNAL_ERROR"; logs the full traceback at ERROR;
   does NOT leak exception type, message, or traceback to the client.

This module uses structlog directly. Once shared/logger is available, the
logger setup will route through it; the handler itself does not change.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from shared.error_handler.exceptions import MaisysException
from shared.error_handler.response import APIResponse, ErrorDetail

_logger = structlog.get_logger(__name__)


def setup_exception_handlers(app: FastAPI) -> None:
    """Register MAISYS exception handlers on the FastAPI app.

    Idempotent: registering on the same app twice is safe (FastAPI replaces
    the previous handler for the same exception class).
    """

    @app.exception_handler(MaisysException)
    async def _handle_maisys_exception(
        request: Request, exc: MaisysException
    ) -> JSONResponse:
        # Fill correlation_id from request state if the exception didn't carry one
        correlation_id = exc.correlation_id or getattr(
            request.state, "request_id", None
        )
        if correlation_id is not None:
            exc.correlation_id = correlation_id

        log_method = _logger.warning if exc.status_code < 500 else _logger.error
        log_method(
            "request.exception",
            code=exc.code,
            status_code=exc.status_code,
            message=exc.message,
            details=exc.details,
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
        )

        response = APIResponse[None].error_from_exception(exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=response.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "request_id", None)
        _logger.error(
            "request.unhandled_exception",
            exc_info=exc,
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
        )
        # Do NOT leak exception type, message, or traceback to the client.
        generic_error = ErrorDetail(
            code="INTERNAL_ERROR",
            message="An internal error occurred",
            details={},
            correlation_id=correlation_id,
        )
        response: APIResponse[None] = APIResponse(
            success=False, data=None, error=generic_error, metadata={}
        )
        return JSONResponse(
            status_code=500,
            content=response.model_dump(mode="json"),
        )
