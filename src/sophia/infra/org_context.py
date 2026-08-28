"""Ambient tenancy scope for database work.

Lives in ``infra`` rather than ``api`` so the engine can read it without the
persistence layer depending on the web layer. The API middleware pushes the
request's org into it; background tasks and the CLI push their own.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT_ORG_ID = "local"

_org_id: ContextVar[str] = ContextVar("sophia_org_id", default=DEFAULT_ORG_ID)


def get_org_id() -> str:
    """Return the org scope database work should run under."""
    return _org_id.get()


def set_org_id(org_id: str) -> object:
    """Set the ambient org scope, returning a token for ``reset_org_id``."""
    return _org_id.set(org_id)


def reset_org_id(token: object) -> None:
    """Restore the org scope a matching ``set_org_id`` replaced."""
    _org_id.reset(token)  # pyright: ignore[reportArgumentType]


@contextlib.contextmanager
def org_scope(org_id: str) -> Iterator[None]:
    """Run a block under an explicit org scope."""
    token = set_org_id(org_id)
    try:
        yield
    finally:
        reset_org_id(token)
