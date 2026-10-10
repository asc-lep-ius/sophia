"""Lecture module ownership: what discovery persists and what search reads back."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import insert, select

from sophia.domain.models import Course, CourseSection, Lecture, ModuleInfo
from sophia.infra.schema import DEFAULT_SCOPE, lecture_downloads, lecture_modules, transcriptions
from sophia.services.hermes_catalog import (
    discover_lecture_module_course,
    discover_lecture_modules,
    get_lecture_module_course_id,
    get_lecture_modules,
    lecture_module_course,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_COURSE = Course(id=12, fullname="Numerical Methods", shortname="NUM")
_OPENCAST_MODULE = ModuleInfo(id=456, name="Opencast Videos", modname="opencast")
_EPISODE = Lecture(episode_id="e1", title="Calibration", series_id="s1")


def _container() -> MagicMock:
    container = MagicMock()
    container.moodle = AsyncMock()
    container.opencast = AsyncMock()
    container.moodle.get_enrolled_courses.return_value = [_COURSE]
    container.moodle.get_course_content.return_value = [
        CourseSection(id=1, name="S1", summary="", modules=[_OPENCAST_MODULE]),
    ]
    container.opencast.get_series_episodes.return_value = [_EPISODE]
    return container


async def _insert_module(db: AsyncSession, module_id: int, **values: object) -> None:
    await db.execute(
        insert(lecture_modules).values(
            module_id=module_id,
            course_name="Numerical Methods",
            course_shortname="NUM",
            **values,
        ),
    )


@pytest.mark.asyncio
async def test_discovery_persists_the_owning_course(db: AsyncSession) -> None:
    await discover_lecture_modules(_container(), db)

    course_id = await db.scalar(
        select(lecture_modules.c.course_id).where(lecture_modules.c.module_id == 456),
    )
    assert course_id == "12"


@pytest.mark.asyncio
async def test_rediscovery_refreshes_a_stale_owner(db: AsyncSession) -> None:
    await _insert_module(db, 456, course_id=DEFAULT_SCOPE)

    await discover_lecture_modules(_container(), db)

    assert await get_lecture_module_course_id(db, 456) == "12"


@pytest.mark.asyncio
async def test_owner_of_a_scoped_module_is_its_course_not_its_id(db: AsyncSession) -> None:
    await _insert_module(db, 456, course_id="12")

    assert await get_lecture_module_course_id(db, 456) == "12"


@pytest.mark.asyncio
async def test_unknown_module_has_no_owner(db: AsyncSession) -> None:
    assert await get_lecture_module_course_id(db, 456) is None


@pytest.mark.asyncio
async def test_pre_tenancy_module_has_no_owner(db: AsyncSession) -> None:
    """A row still at DEFAULT_SCOPE names no course, so it cannot prove one."""
    await _insert_module(db, 456, course_id=DEFAULT_SCOPE)

    assert await get_lecture_module_course_id(db, 456) is None


@pytest.mark.asyncio
async def test_the_cli_finds_an_undiscovered_modules_course_by_discovering(
    db: AsyncSession,
) -> None:
    """A module the browser never scanned still files its study data under its course."""
    container = _container()

    assert await discover_lecture_module_course(container, db, 456) == 12
    assert await lecture_module_course(db, 456) == 12


@pytest.mark.asyncio
async def test_a_recorded_owner_is_used_without_scanning_again(db: AsyncSession) -> None:
    await _insert_module(db, 456, course_id="12")
    container = _container()

    assert await discover_lecture_module_course(container, db, 456) == 12
    container.moodle.get_enrolled_courses.assert_not_called()


@pytest.mark.asyncio
async def test_a_module_in_no_enrolled_course_has_no_course(db: AsyncSession) -> None:
    assert await discover_lecture_module_course(_container(), db, 789) is None


@pytest.mark.asyncio
async def test_catalogue_lists_modules_known_only_through_caption_transcripts(
    db: AsyncSession,
) -> None:
    """A module whose every lecture was captioned has no download row to be found by."""
    await _insert_module(db, 456)
    await db.execute(
        insert(lecture_downloads).values(
            episode_id="e-dl",
            module_id=456,
            series_id="s1",
            title="Downloaded",
            track_url="",
            track_mimetype="",
        ),
    )
    await db.execute(
        insert(transcriptions).values(
            episode_id="e-cc",
            module_id=789,
            status="completed",
            source="captions",
            title="Captioned",
        ),
    )

    modules = await get_lecture_modules(db)

    assert [(m.module_id, m.series_id, m.course_name) for m in modules] == [
        (789, "", ""),
        (456, "s1", "Numerical Methods"),
    ]


@pytest.mark.asyncio
async def test_a_mixed_module_is_listed_once_with_its_series(db: AsyncSession) -> None:
    """Download rows carry the series id; the caption transcript must not add a second row."""
    await db.execute(
        insert(lecture_downloads).values(
            episode_id="e-dl",
            module_id=456,
            series_id="s1",
            title="Downloaded",
            track_url="",
            track_mimetype="",
        ),
    )
    await db.execute(
        insert(transcriptions).values(
            episode_id="e-cc",
            module_id=456,
            status="completed",
            source="captions",
            title="Captioned",
        ),
    )

    modules = await get_lecture_modules(db)

    assert [(m.module_id, m.series_id) for m in modules] == [(456, "s1")]
