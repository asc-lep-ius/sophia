"""Lecture module ownership: what discovery persists and what search reads back."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import insert, select

from sophia.domain.models import Course, CourseSection, Lecture, ModuleInfo
from sophia.infra.schema import DEFAULT_SCOPE, lecture_modules
from sophia.services.hermes_catalog import (
    discover_lecture_modules,
    get_lecture_module_course_id,
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
