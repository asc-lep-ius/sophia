"""Per-course processing settings — whether new recordings follow, and in what language.

Both live on ``learning_path_settings``, the row a course's other pedagogy
settings already share. A course with no row yet gets one with the defaults
the schema declares, so saving one setting never has to invent the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.infra.schema import learning_path_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class IngestionSettings:
    """How a course is processed.

    ``transcription_language`` is ``None`` when Whisper should detect each
    lecture's language itself, which is the default: correct for a course
    taught in another language with nothing to set up first (#128).
    """

    course_id: int
    subscribed: bool = False
    transcription_language: str | None = None


async def get_ingestion_settings(session: AsyncSession, course_id: int) -> IngestionSettings:
    row = (
        await session.execute(
            select(
                learning_path_settings.c.ingestion_subscribed,
                learning_path_settings.c.transcription_language,
            ).where(learning_path_settings.c.course_id == course_id)
        )
    ).one_or_none()
    if row is None:
        return IngestionSettings(course_id=course_id)
    return IngestionSettings(
        course_id=course_id,
        subscribed=row.ingestion_subscribed,
        transcription_language=row.transcription_language,
    )


async def save_ingestion_settings(
    session: AsyncSession,
    settings: IngestionSettings,
) -> IngestionSettings:
    """Upsert the processing settings, leaving the row's other columns as they are."""
    statement = pg_insert(learning_path_settings).values(
        course_id=settings.course_id,
        ingestion_subscribed=settings.subscribed,
        transcription_language=settings.transcription_language,
        updated_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[learning_path_settings.c.course_id],
            set_={
                "ingestion_subscribed": statement.excluded.ingestion_subscribed,
                "transcription_language": statement.excluded.transcription_language,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )
    return settings


async def subscribed_course_ids(session: AsyncSession) -> list[int]:
    """Every course whose new recordings are processed without being asked."""
    return list(
        await session.scalars(
            select(learning_path_settings.c.course_id)
            .where(learning_path_settings.c.ingestion_subscribed.is_(True))
            .order_by(learning_path_settings.c.course_id)
        )
    )
