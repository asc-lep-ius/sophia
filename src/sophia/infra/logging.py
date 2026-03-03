"""Structured logging setup via structlog."""

from __future__ import annotations

import logging

import structlog


def setup_logging(*, debug: bool = False) -> None:
    """Configure structlog with dev (console) or prod (JSON) rendering."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO,
        ),
    )
