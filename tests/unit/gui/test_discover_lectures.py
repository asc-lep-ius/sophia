"""Tests for discover_lecture_modules — Moodle+Opencast discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sophia.domain.models import Course, CourseSection, Lecture, ModuleInfo
from sophia.gui.services.hermes_service import DiscoveredModule, discover_lecture_modules


def _make_container(
    *,
    courses: list[Course] | None = None,
    sections_by_course: list[list[CourseSection]] | None = None,
    episodes_by_module: dict[int, list[Lecture]] | None = None,
) -> MagicMock:
    """Build a fake AppContainer with mocked moodle/opencast."""
    container = MagicMock()
    container.moodle = AsyncMock()
    container.opencast = AsyncMock()
    container.moodle.get_enrolled_courses.return_value = courses or []
    container.moodle.get_course_content.side_effect = sections_by_course or []
    episodes = episodes_by_module or {}
    container.opencast.get_series_episodes.side_effect = lambda mid: episodes.get(mid, [])
    return container


_COURSE_A = Course(id=1, fullname="Analysis 1", shortname="ANA1")
_COURSE_B = Course(id=2, fullname="Algebra", shortname="ALG")

_OC_MODULE = ModuleInfo(id=100, name="Opencast Videos", modname="opencast")
_OC_MODULE_2 = ModuleInfo(id=200, name="Recordings", modname="opencast")
_NON_OC_MODULE = ModuleInfo(id=300, name="Forum", modname="forum")

_EP1 = Lecture(episode_id="e1", title="Lec 1", series_id="s1")
_EP2 = Lecture(episode_id="e2", title="Lec 2", series_id="s1")


class TestDiscoverLectureModules:
    """Verify discover_lecture_modules queries Moodle+Opencast correctly."""

    @pytest.mark.asyncio
    async def test_returns_modules_with_episodes(self) -> None:
        sections = [CourseSection(id=1, name="S1", summary="", modules=[_OC_MODULE])]
        container = _make_container(
            courses=[_COURSE_A],
            sections_by_course=[sections],
            episodes_by_module={100: [_EP1, _EP2]},
        )

        result = await discover_lecture_modules(container)

        assert result == [
            DiscoveredModule(
                course_shortname="ANA1",
                course_fullname="Analysis 1",
                module_id=100,
                module_name="Opencast Videos",
                episode_count=2,
            ),
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_courses(self) -> None:
        container = _make_container(courses=[])
        assert await discover_lecture_modules(container) == []

    @pytest.mark.asyncio
    async def test_skips_non_opencast_modules(self) -> None:
        sections = [CourseSection(id=1, name="S", summary="", modules=[_NON_OC_MODULE])]
        container = _make_container(
            courses=[_COURSE_A],
            sections_by_course=[sections],
        )

        assert await discover_lecture_modules(container) == []

    @pytest.mark.asyncio
    async def test_skips_modules_with_zero_episodes(self) -> None:
        sections = [CourseSection(id=1, name="S", summary="", modules=[_OC_MODULE])]
        container = _make_container(
            courses=[_COURSE_A],
            sections_by_course=[sections],
            episodes_by_module={100: []},
        )

        assert await discover_lecture_modules(container) == []

    @pytest.mark.asyncio
    async def test_multiple_courses_and_modules(self) -> None:
        sections_a = [CourseSection(id=1, name="S", summary="", modules=[_OC_MODULE])]
        sections_b = [
            CourseSection(id=2, name="S", summary="", modules=[_NON_OC_MODULE, _OC_MODULE_2]),
        ]
        container = _make_container(
            courses=[_COURSE_A, _COURSE_B],
            sections_by_course=[sections_a, sections_b],
            episodes_by_module={100: [_EP1], 200: [_EP1, _EP2]},
        )

        result = await discover_lecture_modules(container)

        assert len(result) == 2
        assert result[0].module_id == 100
        assert result[0].episode_count == 1
        assert result[1].module_id == 200
        assert result[1].episode_count == 2
