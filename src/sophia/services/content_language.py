"""Content language resolution for a learning path.

The fallback order is deliberate and is the whole point of the misuse case:
an explicit ``?lang=`` override wins, otherwise the learning path's own exam
language decides. The user's UI locale is never consulted — a learner reading
the interface in English still studies for a German exam in German.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.learning import (
    ContentKind,
    ContentLanguage,
    ContentTranslation,
    LearningPathSettings,
    StoredContentOrigin,
)
from sophia.infra.schema import content_translations, learning_path_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.domain.models import Course


@dataclass(frozen=True, slots=True)
class ResolvedContentLanguage:
    """The language content should be served in, and which rung decided it."""

    language: ContentLanguage
    resolved_from: str


OVERRIDE = "override"
LEARNING_PATH = "learning_path"
DEFAULT = "default"


async def resolve_content_language(
    session: AsyncSession,
    course_id: int,
    *,
    override: ContentLanguage | None,
    default_language: ContentLanguage,
) -> ResolvedContentLanguage:
    """Resolve the content language for a learning path."""
    if override is not None:
        return ResolvedContentLanguage(language=override, resolved_from=OVERRIDE)

    settings = await get_learning_path_settings(session, course_id)
    if settings is not None:
        return ResolvedContentLanguage(
            language=settings.exam_language,
            resolved_from=LEARNING_PATH,
        )
    return ResolvedContentLanguage(language=default_language, resolved_from=DEFAULT)


async def get_learning_path_settings(
    session: AsyncSession,
    course_id: int,
) -> LearningPathSettings | None:
    """Load the persisted pedagogy settings for one learning path."""
    row = (
        await session.execute(
            select(learning_path_settings).where(
                learning_path_settings.c.course_id == course_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return LearningPathSettings(
        course_id=row.course_id,
        exam_language=ContentLanguage(row.exam_language),
        content_origin=StoredContentOrigin(row.content_origin),
    )


async def save_learning_path_settings(
    session: AsyncSession,
    settings: LearningPathSettings,
) -> LearningPathSettings:
    """Upsert the exam language and origin a learning path was ingested from."""
    statement = pg_insert(learning_path_settings).values(
        course_id=settings.course_id,
        exam_language=settings.exam_language.value,
        content_origin=settings.content_origin.value,
        updated_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[learning_path_settings.c.course_id],
            set_={
                "exam_language": statement.excluded.exam_language,
                "content_origin": statement.excluded.content_origin,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )
    return settings


async def get_translations(
    session: AsyncSession,
    course_id: int,
) -> list[ContentTranslation]:
    """Load recorded translations for a learning path.

    Reserved: nothing writes ``content_translations`` until the translation
    pipeline ships, so this returns an empty list in practice. It exists so the
    API shape is stable before the feature lands.
    """
    rows = (
        await session.execute(
            select(content_translations)
            .where(content_translations.c.course_id == course_id)
            .order_by(content_translations.c.translated_at.desc())
        )
    ).all()
    return [
        ContentTranslation(
            content_kind=ContentKind(row.content_kind),
            content_id=row.content_id,
            language=ContentLanguage(row.language),
            translated_at=row.translated_at.isoformat() if row.translated_at else "",
        )
        for row in rows
    ]


async def sync_learning_path_settings(
    session: AsyncSession,
    courses: Sequence[Course],
) -> int:
    """Persist the exam language the upstream source reports for each course.

    Courses whose upstream language is unknown are skipped rather than pinned to
    a guess, so the configured default keeps applying until the source says
    otherwise.
    """
    stored = 0
    for course in courses:
        if course.exam_language is None:
            continue
        await save_learning_path_settings(
            session,
            LearningPathSettings(
                course_id=course.id,
                exam_language=ContentLanguage(course.exam_language),
                content_origin=StoredContentOrigin.TUWEL,
            ),
        )
        stored += 1
    return stored
