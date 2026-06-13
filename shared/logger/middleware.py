"""ASGI middleware that wires request-scoped logging context.

On each HTTP request:
1. Generate a request_id (uuid4) or use the incoming X-Request-ID header.
2. Set request.state.request_id (read by shared.error_handler for correlation_id).
3. Bind {request_id, method, path, service} to structlog contextvars so every
   log line emitted during the request includes them.
4. Log "request.started" at INFO.
5. After the response, log "request.completed" with status_code + duration_ms.
6. On unhandled exception, log "request.failed" at ERROR (with exc_info) and
   re-raise (the global exception handler converts it to a response).
7. Always unbind the contextvars in a finally block.
8. Echo X-Request-ID back to the client in the response headers.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from shared.logger.config import get_logger

_REQUEST_ID_HEADER = "X-Request-ID"
_logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that binds request-scoped log context."""

    def __init__(self, app: ASGIApp, service_name: str = "unknown") -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            service=self.service_name,
        )

        start_time = time.monotonic()
        try:
            _logger.info("request.started")
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            _logger.exception("request.failed", duration_ms=duration_ms)
            raise
        else:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            _logger.info(
                "request.completed",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            response.headers[_REQUEST_ID_HEADER] = request_id
            return response
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "method", "path", "service")
