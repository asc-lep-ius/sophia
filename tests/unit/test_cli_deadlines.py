"""Tests for the Chronos deadline CLI commands.

``sophia deadlines estimate`` reads a row and destructures it, which is exactly
the shape that broke silently when the query moved from hand-written SQL to a
Core expression: ``select(table)`` returns every column, so a query that grows a
column changes what the command unpacks. These tests drive the command against
a real row so that stays honest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .._fakes import with_session
from .._sql import exec_sql

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

DEADLINE_ID = "assign:1"


@pytest.fixture
def app_container(db: AsyncSession) -> MagicMock:
    container = MagicMock()
    container.db = db
    return with_session(container)


async def _insert_deadline(db: AsyncSession) -> None:
    await exec_sql(
        db,
        "INSERT INTO deadline_cache "
        "(id, name, course_id, course_name, deadline_type, due_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (DEADLINE_ID, "Assignment 3", 42, "Linear Algebra", "assignment", "2026-09-30T23:59:00Z"),
    )


@pytest.fixture
def created_app(app_container: MagicMock) -> AbstractContextManager[MagicMock]:
    """Patch ``create_app`` to yield the container wired to the real session."""
    created = MagicMock()
    created.__aenter__ = AsyncMock(return_value=app_container)
    created.__aexit__ = AsyncMock(return_value=False)
    return patch("sophia.infra.di.create_app", return_value=created)


@pytest.mark.asyncio
async def test_estimate_reads_the_named_deadline_columns(
    db: AsyncSession,
    created_app: AbstractContextManager[MagicMock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command must survive deadline_cache carrying more than four columns."""
    from sophia.cli.deadlines import deadlines_estimate

    await _insert_deadline(db)

    with (
        created_app,
        patch("builtins.input", return_value="4"),
        patch(
            "sophia.services.chronos.get_scaffold_level",
            new_callable=AsyncMock,
        ) as scaffold,
        patch(
            "sophia.services.chronos.format_reference_class_hint",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch("sophia.services.chronos.record_estimate", new_callable=AsyncMock) as record,
    ):
        from sophia.domain.models import EstimationScaffold

        scaffold.return_value = EstimationScaffold.MINIMAL
        record.return_value = MagicMock(predicted_hours=4.0, scaffold_level="minimal")

        await deadlines_estimate(DEADLINE_ID)

    # Ordering, not mere presence: both values are in the panel either way, so
    # only their positions catch name and course_name being swapped.
    output = capsys.readouterr().out
    assert output.index("Assignment 3") < output.index("Linear Algebra")
    assert record.await_args is not None
    assert record.await_args.kwargs["course_id"] == 42


@pytest.mark.asyncio
async def test_estimate_exits_when_the_deadline_is_unknown(
    db: AsyncSession,
    created_app: AbstractContextManager[MagicMock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sophia.cli.deadlines import deadlines_estimate

    with created_app, pytest.raises(SystemExit):
        await deadlines_estimate("assign:missing")

    assert "not found" in capsys.readouterr().out
