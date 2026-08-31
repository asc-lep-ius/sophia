"""Shared fakes for tests that mock the application container.

The container hands out sessions rather than exposing a connection, so a mock
has to do the same or the code under test receives an unusable
``MagicMock.session().__aenter__()``. :func:`with_session` wires a mock so that
``container.session()`` yields whatever ``container.db`` is, which keeps the
existing "the service got the database we gave it" assertions meaningful.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


@contextlib.asynccontextmanager
async def _scope(db: object) -> AsyncIterator[object]:
    yield db


def with_session[T](container: T) -> T:
    """Give a mock container a ``session()`` that yields its ``db``."""
    container.session = lambda **_kwargs: _scope(container.db)  # pyright: ignore[reportAttributeAccessIssue]
    return container


def fake_result(rows: Sequence[Any]) -> MagicMock:
    """Fake a SQLAlchemy ``Result`` over ``rows``.

    ``Result`` is sync even on an ``AsyncSession`` — only ``execute`` awaits —
    so an ``AsyncMock`` return value would hand the code a coroutine where it
    expects a row list.
    """
    result = MagicMock()
    result.all.return_value = list(rows)
    result.fetchall.return_value = list(rows)
    result.scalars.return_value.all.return_value = list(rows)
    result.one_or_none.return_value = rows[0] if rows else None
    result.first.return_value = rows[0] if rows else None
    # Anything not stubbed above would hand back a truthy MagicMock and let a
    # broken test pass, so make the unsupported accessors say so instead.
    for unsupported in ("scalar", "scalar_one", "scalar_one_or_none", "mappings", "one"):
        getattr(result, unsupported).side_effect = NotImplementedError(
            f"fake_result does not model .{unsupported}() — stub it or use a real session"
        )
    return result


def fake_row(**fields: Any) -> SimpleNamespace:
    """A row that answers named attribute access the way a ``Row`` does."""
    return SimpleNamespace(**fields)


def session_returning(*results: Sequence[Any]) -> AsyncMock:
    """A session whose successive ``execute`` calls yield ``results`` in order."""
    db = AsyncMock()
    db.execute.side_effect = [fake_result(rows) for rows in results]
    return db
