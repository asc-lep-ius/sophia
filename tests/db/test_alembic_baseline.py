"""The Alembic baseline matches the metadata and reverses cleanly."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from sophia.infra.alembic_runner import (
    current_revision,
    downgrade,
    head_revision,
    is_up_to_date,
    upgrade,
)
from sophia.infra.schema import metadata

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres


def _schema_diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    return list(compare_metadata(context, metadata))


async def test_migrated_database_has_no_drift_from_the_metadata(
    engine: AsyncEngine,
) -> None:
    """The proof that the hand-reviewed baseline still describes the schema."""
    async with engine.connect() as connection:
        diff = await connection.run_sync(_schema_diff)

    assert diff == []


async def test_every_modelled_table_exists(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))

    assert set(metadata.tables) <= tables


async def test_database_is_stamped_at_head(engine: AsyncEngine, migrated_database: str) -> None:
    assert await current_revision(engine) == head_revision(migrated_database)
    assert await is_up_to_date(engine, migrated_database) is True


async def test_booleans_are_real_booleans_not_integers(engine: AsyncEngine) -> None:
    """SQLite stored these as 0/1; Postgres must reject a non-boolean."""
    async with engine.connect() as connection:
        column_type = await connection.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'downloads' AND column_name = 'is_open_access'"
            )
        )

    assert column_type == "boolean"


async def test_declared_timestamps_carry_a_time_zone(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        column_type = await connection.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'learning_events' AND column_name = 'occurred_at'"
            )
        )

    assert column_type == "timestamp with time zone"


async def test_cascade_delete_survived_the_port(engine: AsyncEngine) -> None:
    """content_source_spans.provenance_id was ON DELETE CASCADE in SQLite."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO content_provenance "
                "(id, content_kind, content_id, course_id, generated_by) "
                "VALUES (9001, 'question', 'q-cascade', 12, 'model')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO content_source_spans (provenance_id, content_item_id) "
                "VALUES (9001, 'item-1')"
            )
        )
        await connection.execute(text("DELETE FROM content_provenance WHERE id = 9001"))
        remaining = await connection.scalar(
            text("SELECT count(*) FROM content_source_spans WHERE provenance_id = 9001")
        )

    assert remaining == 0


async def test_check_constraints_survived_the_port(engine: AsyncEngine) -> None:
    """predicted BETWEEN 0.0 AND 1.0 was a SQLite CHECK; it must still bite."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO confidence_ratings (topic, course_id, predicted) "
                    "VALUES ('Graphs', 12, 4.2)"
                )
            )


def test_baseline_downgrades_and_reapplies(migrated_database: str) -> None:
    """A migration that cannot be reversed is not a migration, it is a one-way door."""
    downgrade(migrated_database, "base")
    upgrade(migrated_database, "head")
