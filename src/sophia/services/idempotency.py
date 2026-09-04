"""Idempotent-insert helper shared by the study realtime submission endpoints.

Predictions, self-explanations, reflections, and flashcard saves made during a
live study session each carry a client-generated ``request_id``. A retried
submission (the client never saw the first response, or its outbox replays a
request) must return the row the first attempt created, not a second one — and
that has to hold across concurrent retries and worker restarts, so it is
enforced by a Postgres unique constraint via ``INSERT ... ON CONFLICT DO
NOTHING``, not an in-process cache. See ``services/learning_events.py::
ingest_events`` for the precedent this generalizes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Column, Row, Table
    from sqlalchemy.ext.asyncio import AsyncSession


async def insert_or_fetch_row(
    session: AsyncSession,
    table: Table,
    values: dict[str, object],
    *,
    conflict_columns: Sequence[Column[object]],
    session_id: int,
    user_id: str,
    request_id: str,
) -> tuple[Row[tuple[object, ...]], bool]:
    """Insert one row idempotently. Returns ``(row, is_new)``.

    ``is_new`` is False when ``request_id`` already matched a row from an
    earlier submission: the row returned is the original, and callers must not
    repeat any side effect (a calibration write, an event-log append) that
    already ran for it.
    """
    inserted = (
        await session.execute(
            pg_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=list(conflict_columns))
            .returning(table)
        )
    ).one_or_none()
    if inserted is not None:
        return inserted, True

    # Not filtered by org_id: nothing in this codebase sets it explicitly on
    # insert (every row takes the column's own "default" server_default), and
    # the session-level app.org_id Postgres setting is a separate, currently
    # unrelated concept (still "local" everywhere — see infra/org_context.py).
    # Filtering here against either would only produce a mismatch, not real
    # tenant isolation; session_id already disambiguates uniquely regardless.
    existing = (
        await session.execute(
            select(table).where(
                table.c.session_id == session_id,
                table.c.user_id == user_id,
                table.c.request_id == request_id,
            )
        )
    ).one()
    return existing, False
