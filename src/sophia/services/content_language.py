"""Content language resolution for a learning path.

The fallback order is deliberate and is the whole point of the misuse case:
an explicit ``?lang=`` override wins, otherwise the learning path's own exam
language decides. The user's UI locale is never consulted — a learner reading
the interface in English still studies for a German exam in German.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sophia.domain.learning import (
    ContentKind,
    ContentLanguage,
    ContentTranslation,
    LearningPathSettings,
    StoredContentOrigin,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiosqlite

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
    db: aiosqlite.Connection,
    course_id: int,
    *,
    override: ContentLanguage | None,
    default_language: ContentLanguage,
) -> ResolvedContentLanguage:
    """Resolve the content language for a learning path."""
    if override is not None:
        return ResolvedContentLanguage(language=override, resolved_from=OVERRIDE)

    settings = await get_learning_path_settings(db, course_id)
    if settings is not None:
        return ResolvedContentLanguage(
            language=settings.exam_language,
            resolved_from=LEARNING_PATH,
        )
    return ResolvedContentLanguage(language=default_language, resolved_from=DEFAULT)


async def get_learning_path_settings(
    db: aiosqlite.Connection,
    course_id: int,
) -> LearningPathSettings | None:
    """Load the persisted pedagogy settings for one learning path."""
    cursor = await db.execute(
        "SELECT course_id, exam_language, content_origin FROM learning_path_settings "
        "WHERE course_id = ?",
        (course_id,),
    )
    row = cast("tuple[object, ...] | None", await cursor.fetchone())
    if row is None:
        return None
    return LearningPathSettings(
        course_id=int(cast("int", row[0])),
        exam_language=ContentLanguage(str(row[1])),
        content_origin=StoredContentOrigin(str(row[2])),
    )


async def save_learning_path_settings(
    db: aiosqlite.Connection,
    settings: LearningPathSettings,
) -> LearningPathSettings:
    """Upsert the exam language and origin a learning path was ingested from."""
    await db.execute(
        "INSERT INTO learning_path_settings (course_id, exam_language, content_origin, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(course_id) DO UPDATE SET "
        "exam_language = excluded.exam_language, "
        "content_origin = excluded.content_origin, "
        "updated_at = excluded.updated_at",
        (
            settings.course_id,
            settings.exam_language.value,
            settings.content_origin.value,
            datetime.now(UTC).isoformat(),
        ),
    )
    await db.commit()
    return settings


async def get_translations(
    db: aiosqlite.Connection,
    course_id: int,
) -> list[ContentTranslation]:
    """Load recorded translations for a learning path.

    Reserved: nothing writes ``content_translations`` until the translation
    pipeline ships, so this returns an empty list in practice. It exists so the
    API shape is stable before the feature lands.
    """
    cursor = await db.execute(
        "SELECT content_kind, content_id, language, translated_at FROM content_translations "
        "WHERE course_id = ? ORDER BY translated_at DESC",
        (course_id,),
    )
    rows = cast("Sequence[tuple[object, ...]]", await cursor.fetchall())
    return [
        ContentTranslation(
            content_kind=ContentKind(str(row[0])),
            content_id=str(row[1]),
            language=ContentLanguage(str(row[2])),
            translated_at=str(row[3] or ""),
        )
        for row in rows
    ]


async def sync_learning_path_settings(
    db: aiosqlite.Connection,
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
            db,
            LearningPathSettings(
                course_id=course.id,
                exam_language=ContentLanguage(course.exam_language),
                content_origin=StoredContentOrigin.TUWEL,
            ),
        )
        stored += 1
    return stored
