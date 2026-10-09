"""Migration 0004: a caption transcript stands without a download row."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from anyio import to_thread
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sophia.infra.alembic_runner import downgrade, upgrade

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres


async def test_a_transcription_needs_no_download_row(clean_engine: AsyncEngine) -> None:
    async with clean_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO transcriptions "
                "(episode_id, module_id, status, source, title, caption_url) "
                "VALUES ('ep-captions', 7, 'completed', 'captions', 'Lecture 1', "
                "'https://cdn.video.tuwien.ac.at/captions.vtt')"
            )
        )
        downloads = await connection.scalar(
            text("SELECT count(*) FROM lecture_downloads WHERE episode_id = 'ep-captions'")
        )
        source = await connection.scalar(
            text("SELECT source FROM transcriptions WHERE episode_id = 'ep-captions'")
        )

    assert downloads == 0
    assert source == "captions"


async def test_existing_rows_read_as_whisper(clean_engine: AsyncEngine) -> None:
    async with clean_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO lecture_downloads "
                "(episode_id, module_id, title, track_url, track_mimetype, status) "
                "VALUES ('ep-whisper', 7, 'Lecture 2', '', '', 'completed')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO transcriptions (episode_id, module_id, status) "
                "VALUES ('ep-whisper', 7, 'completed')"
            )
        )
        source = await connection.scalar(
            text("SELECT source FROM transcriptions WHERE episode_id = 'ep-whisper'")
        )

    assert source == "whisper"


async def test_source_is_one_of_the_two_known_origins(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO transcriptions (episode_id, module_id, status, source) "
                    "VALUES ('ep-odd', 7, 'completed', 'dictation')"
                )
            )


_FK_EXISTS = text(
    "SELECT count(*) FROM information_schema.table_constraints "
    "WHERE table_name = 'transcriptions' "
    "AND constraint_name = 'fk_transcriptions_episode_id_lecture_downloads'"
)


async def test_downgrade_removes_caption_rows_and_restores_the_download_key(
    clean_engine: AsyncEngine, migrated_database: str
) -> None:
    """The one-way door 0004 opens is reversed by deleting what cannot pass back through it."""
    async with clean_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO transcriptions (episode_id, module_id, status, source, title) "
                "VALUES ('ep-cc', 7, 'completed', 'captions', 'Captioned')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO transcript_segments "
                "(episode_id, segment_index, start_time, end_time, text) "
                "VALUES ('ep-cc', 0, 0.0, 1.0, 'cue')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_index (episode_id, module_id, status) "
                "VALUES ('ep-cc', 7, 'failed')"
            )
        )
    await clean_engine.dispose()

    # Alembic's env.py opens its own event loop, so it runs on a worker thread.
    await to_thread.run_sync(downgrade, migrated_database, "0003_study_session_scoring")
    try:
        async with clean_engine.connect() as connection:
            transcriptions = await connection.scalar(
                text("SELECT count(*) FROM transcriptions WHERE episode_id = 'ep-cc'")
            )
            segments = await connection.scalar(
                text("SELECT count(*) FROM transcript_segments WHERE episode_id = 'ep-cc'")
            )
            index_rows = await connection.scalar(
                text("SELECT count(*) FROM knowledge_index WHERE episode_id = 'ep-cc'")
            )
            fk_count = await connection.scalar(_FK_EXISTS)
    finally:
        await clean_engine.dispose()
        await to_thread.run_sync(upgrade, migrated_database, "head")

    assert (transcriptions, segments, index_rows) == (0, 0, 0)
    assert fk_count == 1
