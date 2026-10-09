"""Migration 0004: a caption transcript stands without a download row."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
