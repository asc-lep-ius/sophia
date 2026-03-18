"""Tests for CLI course identifier → Opencast module ID resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sophia.domain.models import Course, CourseSection, ModuleInfo


def _make_courses() -> list[Course]:
    """Sample enrolled courses for testing."""
    return [
        Course(
            id=100,
            fullname="Algorithmen und Datenstrukturen 1",
            shortname="186.813 AlgDat1 2026S",
            url="https://tuwel.tuwien.ac.at/course/view.php?id=100",
        ),
        Course(
            id=200,
            fullname="Technische Grundlagen der Informatik",
            shortname="182.692 TGI 2026S",
            url="https://tuwel.tuwien.ac.at/course/view.php?id=200",
        ),
        Course(
            id=300,
            fullname="Analysis für Informatik",
            shortname="104.271 Analysis 2026S",
            url="https://tuwel.tuwien.ac.at/course/view.php?id=300",
        ),
    ]


def _opencast_section(module_id: int = 42) -> list[CourseSection]:
    """Course content with one Opencast module."""
    return [
        CourseSection(
            id=1,
            name="General",
            summary="",
            modules=[
                ModuleInfo(id=99, name="Announcements", modname="forum", contents=[]),
                ModuleInfo(id=module_id, name="Lectures", modname="opencast", contents=[]),
            ],
        ),
    ]


def _no_opencast_section() -> list[CourseSection]:
    """Course content without any Opencast module."""
    return [
        CourseSection(
            id=1,
            name="General",
            summary="",
            modules=[
                ModuleInfo(id=99, name="Announcements", modname="forum", contents=[]),
            ],
        ),
    ]


def _mock_moodle(
    courses: list[Course] | None = None,
    content_map: dict[int, list[CourseSection]] | None = None,
) -> AsyncMock:
    """Create a mock MoodleClient with predefined responses."""
    mock = AsyncMock()
    mock.get_enrolled_courses.return_value = courses or _make_courses()

    if content_map:
        async def _get_content(course_id: int) -> list[CourseSection]:
            return content_map.get(course_id, _no_opencast_section())
        mock.get_course_content.side_effect = _get_content
    else:
        mock.get_course_content.return_value = _opencast_section()

    return mock


# --- Raw integer ---


@pytest.mark.asyncio
async def test_resolve_raw_integer() -> None:
    """A pure integer string resolves directly — no Moodle calls needed."""
    from sophia.cli._resolver import resolve_module_id

    mock = _mock_moodle()
    result = await resolve_module_id("12345", mock)

    assert result == 12345
    mock.get_enrolled_courses.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_raw_integer_negative() -> None:
    """Negative integers should not be treated as course numbers."""
    from sophia.cli._resolver import resolve_module_id

    mock = _mock_moodle()
    result = await resolve_module_id("-1", mock)

    assert result == -1


# --- Course number ---


@pytest.mark.asyncio
async def test_resolve_course_number() -> None:
    """A TISS course number like '186.813' resolves via enrolled courses."""
    from sophia.cli._resolver import resolve_module_id

    content_map = {100: _opencast_section(module_id=555)}
    mock = _mock_moodle(content_map=content_map)

    result = await resolve_module_id("186.813", mock)

    assert result == 555
    mock.get_enrolled_courses.assert_awaited_once()
    mock.get_course_content.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_resolve_course_number_no_match() -> None:
    """A course number not in any enrolled course raises ValueError."""
    from sophia.cli._resolver import resolve_module_id

    mock = _mock_moodle()

    with pytest.raises(ValueError, match="No enrolled course found with number 999.999"):
        await resolve_module_id("999.999", mock)


# --- Name matching: exact substring ---


@pytest.mark.asyncio
async def test_resolve_name_exact_substring() -> None:
    """An exact substring of a course fullname resolves correctly."""
    from sophia.cli._resolver import resolve_module_id

    content_map = {100: _opencast_section(module_id=777)}
    mock = _mock_moodle(content_map=content_map)

    result = await resolve_module_id("Algorithmen", mock)

    assert result == 777


@pytest.mark.asyncio
async def test_resolve_name_case_insensitive() -> None:
    """Name matching is case-insensitive."""
    from sophia.cli._resolver import resolve_module_id

    content_map = {200: _opencast_section(module_id=888)}
    mock = _mock_moodle(content_map=content_map)

    result = await resolve_module_id("technische grundlagen", mock)

    assert result == 888


# --- Name matching: fuzzy ---


@pytest.mark.asyncio
async def test_resolve_name_fuzzy() -> None:
    """A fuzzy fragment like 'AlgDat' matches 'Algorithmen und Datenstrukturen 1'."""
    from sophia.cli._resolver import resolve_module_id

    # "AlgDat" isn't a substring of "Algorithmen und Datenstrukturen 1"
    # but the shortname contains it — we need to ensure fuzzy match works
    content_map = {100: _opencast_section(module_id=999)}
    mock = _mock_moodle(content_map=content_map)

    # Use a fragment that appears nowhere literally but fuzzy-matches
    result = await resolve_module_id("AlgDat", mock)

    assert result == 999


# --- Ambiguous ---


@pytest.mark.asyncio
async def test_resolve_ambiguous_substring() -> None:
    """Multiple substring matches raise ValueError listing candidates."""
    from sophia.cli._resolver import resolve_module_id

    # Both Course 100 and 300 contain "für" → nope, let's use "Informatik"
    # Course 200 "Technische Grundlagen der Informatik" and Course 300 "Analysis für Informatik"
    mock = _mock_moodle()

    with pytest.raises(ValueError, match="Multiple courses match"):
        await resolve_module_id("Informatik", mock)


# --- No match ---


@pytest.mark.asyncio
async def test_resolve_no_match() -> None:
    """A fragment that matches nothing raises ValueError."""
    from sophia.cli._resolver import resolve_module_id

    mock = _mock_moodle()

    with pytest.raises(ValueError, match="No enrolled course found matching"):
        await resolve_module_id("Quantenphysik", mock)


# --- No Opencast module ---


@pytest.mark.asyncio
async def test_resolve_no_opencast_module() -> None:
    """Course found but no Opencast module raises ValueError."""
    from sophia.cli._resolver import resolve_module_id

    content_map = {100: _no_opencast_section()}
    mock = _mock_moodle(content_map=content_map)

    with pytest.raises(ValueError, match="No Opencast module found"):
        await resolve_module_id("186.813", mock)


# --- Fuzzy matching with shortname fallback ---


@pytest.mark.asyncio
async def test_resolve_fuzzy_checks_shortname() -> None:
    """Fuzzy matching also considers shortname, not just fullname."""
    from sophia.cli._resolver import resolve_module_id

    # "AlgDat1" appears in shortname "186.813 AlgDat1 2026S" but not fullname
    content_map = {100: _opencast_section(module_id=1111)}
    mock = _mock_moodle(content_map=content_map)

    result = await resolve_module_id("AlgDat1", mock)

    assert result == 1111


# --- handle_resolve_error context manager ---


@pytest.mark.asyncio
async def test_handle_resolve_error_converts_valueerror_to_systemexit() -> None:
    """The context manager converts ValueError to SystemExit(1)."""
    from sophia.cli._resolver import handle_resolve_error

    with pytest.raises(SystemExit) as exc_info:
        async with handle_resolve_error():
            msg = "No enrolled course found matching 'xyz'"
            raise ValueError(msg)

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_handle_resolve_error_passes_through_other_exceptions() -> None:
    """Non-ValueError exceptions propagate normally."""
    from sophia.cli._resolver import handle_resolve_error

    with pytest.raises(RuntimeError, match="unrelated"):
        async with handle_resolve_error():
            msg = "unrelated"
            raise RuntimeError(msg)


# --- identifier strip ---


@pytest.mark.asyncio
async def test_resolve_strips_whitespace_course_number() -> None:
    """Leading/trailing whitespace on course number is stripped before matching."""
    from sophia.cli._resolver import resolve_module_id

    content_map = {100: _opencast_section(module_id=555)}
    mock = _mock_moodle(content_map=content_map)

    result = await resolve_module_id("  186.813  ", mock)

    assert result == 555
    # Should resolve via course number path, not fuzzy match
    mock.get_course_content.assert_awaited_once_with(100)


# --- empty fuzzy top list ---


@pytest.mark.asyncio
async def test_resolve_fuzzy_no_good_matches_raises() -> None:
    """When fuzzy scores are all below threshold, raise 'no match' error."""
    from sophia.cli._resolver import resolve_module_id

    # Use a fragment that won't substring-match and won't fuzzy-match well
    mock = _mock_moodle()

    with pytest.raises(ValueError, match="No enrolled course found matching"):
        await resolve_module_id("xyzzyplugh", mock)
