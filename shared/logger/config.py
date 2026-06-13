"""Structlog configuration for MAISYS services.

Call `configure_logging(env, log_level)` once at process startup (typically
the first line of `main.py`). After that, every `get_logger(name)` call
returns a bound logger that flows through the configured processor chain.

Environment modes:
- dev, ci: ConsoleRenderer with colors, human-readable
- stage, prod: JSONRenderer, one JSON object per log line, ready for log
  aggregators (Loki, CloudWatch, etc.)

The stdlib logging integration ensures third-party library logs (FastAPI,
SQLAlchemy, uvicorn, httpx) flow through the same processors with the same
formatting.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog

from shared.logger.processors import scrub_sensitive

Env = Literal["dev", "ci", "stage", "prod"]


def configure_logging(env: str, log_level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for the process.

    Idempotent — calling more than once replaces the previous configuration.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure stdlib root logger so third-party library logs also pass
    # through our formatters. structlog.stdlib.ProcessorFormatter ensures the
    # full processor chain runs on stdlib log records too.
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    pre_chain: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        timestamper,
        scrub_sensitive,
    ]

    if env in ("dev", "ci"):
        final_renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=(env == "dev")
        )
    else:
        final_renderer = structlog.processors.JSONRenderer()

    # Formatter used by stdlib handlers to render structlog event dicts and
    # to render plain stdlib records.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            final_renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Replace any existing handlers to ensure clean idempotency
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    # Quiet some noisy library defaults
    for noisy in ("urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Configure structlog itself
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            timestamper,
            scrub_sensitive,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named bound logger.

    Safe to call before configure_logging — the returned proxy resolves at
    first use after configuration.
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
