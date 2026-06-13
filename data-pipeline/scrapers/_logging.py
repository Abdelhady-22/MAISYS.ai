"""Local structlog configuration for the scrapers.

``shared/logger`` is not built yet; this is the interim console logging setup,
mirroring the pattern in ``data-pipeline/cloud/upload_local_to_gcs.py``. Replace
with ``shared.logger`` once that module lands.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(verbose: bool = False) -> None:
    """Configure structlog for human-readable console output.

    INFO by default; DEBUG when ``verbose``.
    """
    level = logging.DEBUG if verbose else logging.INFO
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return a module-level structlog logger."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger()
    return logger
