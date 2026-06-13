"""MAISYS shared logger module — structured logging across all services.

Provides:
- configure_logging(env, log_level): one-time process-level setup
- get_logger(name): obtain a named bound logger
- RequestLoggingMiddleware: ASGI middleware that wires request-scoped context
- scrub_sensitive: structlog processor that redacts sensitive values

Typical usage in a service's main.py:

    from fastapi import FastAPI
    from shared.logger import configure_logging, RequestLoggingMiddleware

    configure_logging(env="prod", log_level="INFO")
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, service_name="auth-service")

In any module that needs to log:

    from shared.logger import get_logger
    logger = get_logger(__name__)
    logger.info("user.created", user_id=user.id)
"""

from shared.logger.config import configure_logging, get_logger
from shared.logger.middleware import RequestLoggingMiddleware
from shared.logger.processors import scrub_sensitive

__all__ = [
    "RequestLoggingMiddleware",
    "configure_logging",
    "get_logger",
    "scrub_sensitive",
]
