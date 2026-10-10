"""Migration 0005: study rows filed under a module move to the course that owns it.

The seed is EP1 2026W's shape (#127): two modules of one course, 3022060 and
3022498, both owned by course 82774; a module of another course; and a module
no discovery ever recorded an owner for. Every row is written the old way,
under a module id, at revision 0004.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from anyio import to_thread
from sqlalchemy import text

from sophia.infra.alembic_runner import downgrade, upgrade

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

pytestmark = pytest.mark.postgres

_BEFORE = "0004_transcription_source"

_SEED = (
    "INSERT INTO lecture_modules (module_id, course_id) "
    "VALUES (3022060, '82774'), (3022498, '82774'), (2856855, '78417')",
    "INSERT INTO transcriptions (episode_id, module_id, status) "
    "VALUES ('ep-unowned', 9001, 'completed')",
    "INSERT INTO topic_mappings (topic, course_id, source) VALUES "
    "('Schleifen', 3022498, 'lecture'), ('Arrays', 3022498, 'lecture'), "
    "('Rekursion', 3022060, 'lecture'), ('Arrays', 3022060, 'lecture'), "
    "('Strings', 2856855, 'lecture'), ('Unowned', 9001, 'lecture'), "
    "('Graphs', 82774, 'manual')",
    "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES "
    "('Schleifen', 3022498, 0.5), ('Rekursion', 3022060, 0.25), ('Graphs', 82774, 0.75)",
    "INSERT INTO review_schedule (topic, course_id, next_review_at) VALUES "
    "('Schleifen', 3022498, now()), ('Rekursion', 3022060, now())",
    "INSERT INTO topic_lecture_links (topic, course_id, chunk_id, episode_id) VALUES "
    "('Schleifen', 3022498, 'ep-a_0', 'ep-a'), ('Rekursion', 3022060, 'ep-b_0', 'ep-b')",
    "INSERT INTO topic_reconciliations (manual_topic, moodle_topic, course_id, similarity) "
    "VALUES ('Loops', 'Schleifen', 3022498, 0.9)",
)

# Each table's rows as (course_id, what identifies the row within it).
_ROWS = {
    "topic_mappings": "SELECT course_id, topic || '/' || source FROM topic_mappings",
    "confidence_ratings": "SELECT course_id, topic FROM confidence_ratings",
    "review_schedule": "SELECT course_id, topic FROM review_schedule",
    "topic_lecture_links": "SELECT course_id, topic || '/' || chunk_id FROM topic_lecture_links",
    "topic_reconciliations": "SELECT course_id, manual_topic FROM topic_reconciliations",
}

Snapshot = dict[str, list[tuple[int, str]]]


async def _snapshot(connection: AsyncConnection) -> Snapshot:
    return {
        table: sorted((row[0], row[1]) for row in await connection.execute(text(query)))
        for table, query in _ROWS.items()
    }


async def _seed_the_old_way(engine: AsyncEngine, database: str) -> Snapshot:
    await engine.dispose()
    # Alembic's env.py opens its own event loop, so it runs on a worker thread.
    await to_thread.run_sync(downgrade, database, _BEFORE)
    async with engine.begin() as connection:
        for statement in _SEED:
            await connection.execute(text(statement))
        return await _snapshot(connection)


async def _migrate(engine: AsyncEngine, database: str, revision: str) -> Snapshot:
    await engine.dispose()
    if revision == "head":
        await to_thread.run_sync(upgrade, database, revision)
    else:
        await to_thread.run_sync(downgrade, database, revision)
    async with engine.connect() as connection:
        return await _snapshot(connection)


async def test_upgrade_moves_every_owned_row_to_its_course_and_loses_none(
    clean_engine: AsyncEngine, migrated_database: str
) -> None:
    try:
        before = await _seed_the_old_way(clean_engine, migrated_database)
        after = await _migrate(clean_engine, migrated_database, "head")
    finally:
        await clean_engine.dispose()
        await to_thread.run_sync(upgrade, migrated_database, "head")

    assert {table: len(rows) for table, rows in after.items()} == {
        table: len(rows) for table, rows in before.items()
    }
    assert after["topic_mappings"] == [
        # Arrays came from both modules; 3022060's moved, and 3022498's would
        # have collided with it, so it stays rather than being merged away.
        (9001, "Unowned/lecture"),
        (78417, "Strings/lecture"),
        (82774, "Arrays/lecture"),
        (82774, "Graphs/manual"),
        (82774, "Rekursion/lecture"),
        (82774, "Schleifen/lecture"),
        (3022498, "Arrays/lecture"),
    ]
    assert after["confidence_ratings"] == [
        (82774, "Graphs"),
        (82774, "Rekursion"),
        (82774, "Schleifen"),
    ]
    assert after["review_schedule"] == [(82774, "Rekursion"), (82774, "Schleifen")]
    assert after["topic_lecture_links"] == [
        (82774, "Rekursion/ep-b_0"),
        (82774, "Schleifen/ep-a_0"),
    ]
    assert after["topic_reconciliations"] == [(82774, "Loops")]


async def test_downgrade_splits_the_course_back_into_its_two_modules(
    clean_engine: AsyncEngine, migrated_database: str
) -> None:
    """Each row returns to the module it came from; nothing stays merged under 82774."""
    try:
        before = await _seed_the_old_way(clean_engine, migrated_database)
        await _migrate(clean_engine, migrated_database, "head")
        async with clean_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO topic_mappings (topic, course_id, source) "
                    "VALUES ('Written after', 82774, 'lecture')"
                )
            )
        restored = await _migrate(clean_engine, migrated_database, _BEFORE)
        async with clean_engine.connect() as connection:
            rekeys_table = await connection.scalar(
                text("SELECT to_regclass('public.module_course_rekeys')")
            )
    finally:
        await clean_engine.dispose()
        await to_thread.run_sync(upgrade, migrated_database, "head")

    written_after = (82774, "Written after/lecture")
    assert restored == {
        **before,
        "topic_mappings": sorted([*before["topic_mappings"], written_after]),
    }
    assert rekeys_table is None


async def test_a_database_with_no_module_rows_upgrades_untouched(
    clean_engine: AsyncEngine, migrated_database: str
) -> None:
    try:
        await clean_engine.dispose()
        await to_thread.run_sync(downgrade, migrated_database, _BEFORE)
        async with clean_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO topic_mappings (topic, course_id, source) "
                    "VALUES ('Graphs', 82774, 'manual')"
                )
            )
        after = await _migrate(clean_engine, migrated_database, "head")
    finally:
        await clean_engine.dispose()
        await to_thread.run_sync(upgrade, migrated_database, "head")

    assert after["topic_mappings"] == [(82774, "Graphs/manual")]
