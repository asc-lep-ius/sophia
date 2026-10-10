"""Which of a course's recordings a processing job covers (#128).

A module linked on a course's TUWEL page belongs to the course, but its
series may hold recordings from other semesters — last semester's lectures,
linked into this semester's page. Processing those costs hours of GPU time
for lectures the student is not attending, so Process, the scan and the
nightly run cover only recordings dated within the course's own semester.
The rest are one press away: "Process older recordings too" queues a one-off
job over them and changes nothing afterwards.

Semesters follow UG §52: a W semester runs 1 October to the end of February,
an S semester 1 March to 30 September. A recording with no date on the series
page counts as current — the page is the only cheap source of the date, and a
missing one must not hide a lecture.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.tiss import extract_semester
from sophia.infra.schema import (
    lecture_downloads,
    lecture_modules,
    lecture_recordings,
    topic_extractions,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.domain.models import Lecture

log = structlog.get_logger()

CURRENT_SEMESTER = "semester"
OLDER = "older"
SCOPES = (CURRENT_SEMESTER, OLDER)

# Downloads in these states were looked at and deliberately not transcribed;
# a recording in one of them is not waiting for anything.
_SETTLED_DOWNLOAD_STATUSES = ("skipped", "discarded")


def semester_window(semester: str) -> tuple[date, date] | None:
    """The first and last day of ``"2026W"`` or ``"2026S"``; ``None`` for anything else."""
    if len(semester) != 5 or not semester[:4].isdigit() or semester[4] not in "SW":
        return None
    year = int(semester[:4])
    if semester[4] == "S":
        return date(year, 3, 1), date(year, 9, 30)
    last_of_february = calendar.monthrange(year + 1, 2)[1]
    return date(year, 10, 1), date(year + 1, 2, last_of_february)


async def course_semester(session: AsyncSession, course_id: int) -> str | None:
    """The semester discovery recorded for the course, read from its modules' names."""
    rows = (
        await session.execute(
            select(lecture_modules.c.course_shortname, lecture_modules.c.course_name)
            .where(lecture_modules.c.course_id == str(course_id))
            .order_by(lecture_modules.c.module_id)
        )
    ).all()
    for row in rows:
        semester = extract_semester(row.course_shortname, row.course_name)
        if semester is not None:
            return semester
    return None


async def register_recordings(
    session: AsyncSession,
    module_id: int,
    episodes: Sequence[Lecture],
    *,
    course_id: str | None = None,
) -> None:
    """Record what a module's series page lists, with each recording's date."""
    now = datetime.now(UTC)
    for episode in episodes:
        values: dict[str, object] = {
            "episode_id": episode.episode_id,
            "module_id": module_id,
            "title": episode.title,
            "recorded_on": _recorded_on(episode.created),
            "last_seen_at": now,
        }
        if course_id is not None:
            values["course_id"] = course_id
        statement = pg_insert(lecture_recordings).values(**values)
        update_columns = {
            "module_id": statement.excluded.module_id,
            "title": statement.excluded.title,
            "last_seen_at": statement.excluded.last_seen_at,
            # A date read once is kept when a later page shows none.
            "recorded_on": func.coalesce(
                statement.excluded.recorded_on, lecture_recordings.c.recorded_on
            ),
        }
        if course_id is not None:
            update_columns["course_id"] = statement.excluded.course_id
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[lecture_recordings.c.episode_id], set_=update_columns
            )
        )


async def scoped_episode_ids(
    session: AsyncSession,
    course_id: int,
    module_id: int,
    scope: str,
) -> frozenset[str] | None:
    """The module's recordings a job of ``scope`` covers.

    ``None`` means nothing is known to restrict by: the module has no
    registered recordings yet, so the media stage must list the series first.
    With no semester to read from the course's name every recording counts as
    current, so a semester job covers them all and an older job none.
    """
    rows = (
        await session.execute(
            select(lecture_recordings.c.episode_id, lecture_recordings.c.recorded_on).where(
                lecture_recordings.c.module_id == module_id
            )
        )
    ).all()
    if not rows:
        return None
    semester = await course_semester(session, course_id)
    window = semester_window(semester) if semester else None
    if window is None:
        log.warning("ingestion_scope_no_semester", course_id=course_id, module_id=module_id)
        current = frozenset(row.episode_id for row in rows)
    else:
        first, last = window
        current = frozenset(
            row.episode_id
            for row in rows
            if row.recorded_on is None or first <= row.recorded_on <= last
        )
    if scope == CURRENT_SEMESTER:
        return current
    return frozenset(row.episode_id for row in rows) - current


async def older_recordings_pending(session: AsyncSession, course_id: int) -> int:
    """How many of the course's recordings from other semesters have no topics yet.

    Counted until the lecture's topics are extracted, not until it is
    transcribed: the older job covers every stage, and a lecture whose
    indexing or topic extraction failed has to stay one press away, or it
    could never be retried — Process and the nightly never touch it.
    """
    semester = await course_semester(session, course_id)
    window = semester_window(semester) if semester else None
    if window is None:
        return 0
    first, last = window
    course_modules = select(lecture_modules.c.module_id).where(
        lecture_modules.c.course_id == str(course_id)
    )
    count = await session.scalar(
        select(func.count())
        .select_from(lecture_recordings)
        .where(
            lecture_recordings.c.module_id.in_(course_modules),
            lecture_recordings.c.recorded_on.is_not(None),
            (lecture_recordings.c.recorded_on < first) | (lecture_recordings.c.recorded_on > last),
            ~_topics_extracted(lecture_recordings.c.episode_id),
            ~_settled(lecture_recordings.c.episode_id),
        )
    )
    return int(count or 0)


def _topics_extracted(episode_id: ColumnElement[str]) -> ColumnElement[bool]:
    return exists().where(
        topic_extractions.c.episode_id == episode_id, topic_extractions.c.status == "completed"
    )


def _settled(episode_id: ColumnElement[str]) -> ColumnElement[bool]:
    return exists().where(
        lecture_downloads.c.episode_id == episode_id,
        lecture_downloads.c.status.in_(_SETTLED_DOWNLOAD_STATUSES),
    )


def _recorded_on(created: str) -> date | None:
    """The date in ``Lecture.created``: the series page gives a date, the player a timestamp."""
    if len(created) < 10:
        return None
    try:
        return date.fromisoformat(created[:10])
    except ValueError:
        return None
