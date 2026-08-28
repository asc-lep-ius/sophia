"""Structured logging setup via structlog."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    from structlog.typing import EventDict, WrappedLogger

REDACTED_VALUE = "[redacted]"

_SENSITIVE_EXACT_KEYS = frozenset(
    {
        "auth",
        "authorization",
        "card_id",
        "content_text",
        "cookie",
        "email",
        "learner_id",
        "password",
        "prompt",
        "question_id",
        "secret",
        "session_id",
        "set_cookie",
        "token",
        "user_id",
        "x_api_key",
    }
)
_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "content",
    "learner",
    "password",
    "prompt",
    "secret",
    "session",
    "token",
)


def is_sensitive_observability_key(key: object) -> bool:
    """Return whether an observability field name may carry private data."""
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_EXACT_KEYS or any(
        fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS
    )


def redact_sensitive_log_fields(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Redact private values from structured log events before rendering."""
    for key, value in tuple(event_dict.items()):
        event_dict[key] = _redact_value_for_key(key, value)
    return event_dict


def _redact_value_for_key(key: object, value: Any) -> Any:
    if is_sensitive_observability_key(key):
        return REDACTED_VALUE
    return _redact_value(value)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        mapping = cast("dict[object, Any]", value)
        return {key: _redact_value_for_key(key, child) for key, child in mapping.items()}
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [_redact_value(child) for child in items]
    return value


def _add_service_name(
    service_name: str,
) -> Callable[[WrappedLogger, str, EventDict], EventDict]:
    def add_service_name(
        _logger: WrappedLogger,
        _method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        event_dict.setdefault("service", service_name)
        return event_dict

    return add_service_name


def setup_logging(
    *,
    debug: bool = False,
    json_logs: bool = True,
    service_name: str = "sophia",
) -> None:
    """Configure structlog with dev (console) or prod (JSON) rendering."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_service_name(service_name),
            redact_sensitive_log_fields,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.processors.JSONRenderer()
            if json_logs
            else structlog.dev.ConsoleRenderer(colors=debug),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            level,
        ),
        cache_logger_on_first_use=False,
    )
