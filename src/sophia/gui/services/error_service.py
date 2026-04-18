"""Error classification and GUI-safe error-handler decorator."""

from __future__ import annotations

import contextlib
import functools
import inspect
from enum import Enum, auto
from typing import Any

import structlog
from nicegui import ui

from sophia.domain.errors import AuthError, NetworkError, SophiaError

log = structlog.get_logger()


class ErrorCategory(Enum):
    """Broad error categories for UI display."""

    AUTH = auto()
    NETWORK = auto()
    STORAGE = auto()
    DOMAIN = auto()
    UNKNOWN = auto()


def classify_error(exc: Exception) -> ErrorCategory:
    """Map an exception to a broad UI category (most-specific first)."""
    if isinstance(exc, AuthError):
        return ErrorCategory.AUTH
    if isinstance(exc, NetworkError):
        return ErrorCategory.NETWORK
    if isinstance(exc, OSError | PermissionError):
        return ErrorCategory.STORAGE
    if isinstance(exc, SophiaError):
        return ErrorCategory.DOMAIN
    return ErrorCategory.UNKNOWN


def gui_error_handler(*, operation: str, fallback: Any) -> Any:
    """Decorator factory: catch errors, log, show toast, return *fallback*.

    Works with both sync and async callables.
    """

    def decorator(fn: Any) -> Any:
        def _handle_error(exc: Exception, **kwargs: Any) -> Any:
            category = classify_error(exc)
            log.exception(
                f"{operation}_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
                category=category,
                **kwargs,
            )
            with contextlib.suppress(Exception):
                ui.notify(f"{operation}: {exc}", type="negative")
            return fallback

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    return _handle_error(exc, **kwargs)

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                return _handle_error(exc, **kwargs)

        return sync_wrapper

    return decorator
