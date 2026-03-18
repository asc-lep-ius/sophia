"""Resolve course identifiers (number, name fragment, or raw ID) to Opencast module IDs."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from sophia.adapters.tiss import extract_course_info

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sophia.adapters.moodle import MoodleAdapter
    from sophia.domain.models import Course

_COURSE_NUMBER_PATTERN = re.compile(r"^\d{3}\.\d{3}$")


@asynccontextmanager
async def handle_resolve_error() -> AsyncIterator[None]:
    """Catch ``ValueError`` from resolver and convert to a clean CLI exit."""
    try:
        yield
    except ValueError as e:
        from sophia.cli._output import get_console

        get_console().print(f"[red]{e}[/red]")
        raise SystemExit(1) from None


async def resolve_module_id(identifier: str, moodle: MoodleAdapter) -> int:
    """Resolve a course identifier to an Opencast module ID.

    Resolution chain:
    1. Pure integer → module_id directly (backwards compatible)
    2. Pattern ``NNN.NNN`` → TISS course number lookup
    3. Otherwise → fuzzy name matching against enrolled courses
    """
    identifier = identifier.strip()

    try:
        return int(identifier)
    except ValueError:
        pass

    courses = await moodle.get_enrolled_courses()

    if _COURSE_NUMBER_PATTERN.match(identifier):
        return await _resolve_by_course_number(identifier, courses, moodle)

    return await _resolve_by_name(identifier, courses, moodle)


async def _resolve_by_course_number(
    number: str, courses: list[Course], moodle: MoodleAdapter
) -> int:
    """Find the course whose shortname contains the given TISS number."""
    matches = [c for c in courses if number in c.shortname]
    if not matches:
        msg = f"No enrolled course found with number {number}"
        raise ValueError(msg)
    if len(matches) > 1:
        msg = _format_ambiguous(matches, f"course number {number}")
        raise ValueError(msg)
    return await _get_opencast_module(matches[0], moodle)


async def _resolve_by_name(fragment: str, courses: list[Course], moodle: MoodleAdapter) -> int:
    """Match fragment against enrolled course names and shortnames."""
    fragment_lower = fragment.lower()

    # Exact substring match in fullname or shortname
    exact = [
        c
        for c in courses
        if fragment_lower in c.fullname.lower() or fragment_lower in c.shortname.lower()
    ]
    if len(exact) == 1:
        return await _get_opencast_module(exact[0], moodle)
    if len(exact) > 1:
        msg = _format_ambiguous(exact, f"name fragment '{fragment}'")
        raise ValueError(msg)

    # Fuzzy match against fullname + shortname
    scored = [
        (
            c,
            max(
                SequenceMatcher(None, fragment_lower, c.fullname.lower()).ratio(),
                SequenceMatcher(None, fragment_lower, c.shortname.lower()).ratio(),
            ),
        )
        for c in courses
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    if scored and scored[0][1] >= 0.4:
        best = scored[0]
        if len(scored) < 2 or best[1] - scored[1][1] > 0.1:
            return await _get_opencast_module(best[0], moodle)
        top = [c for c, s in scored[:5] if s >= 0.3]
        if not top:
            msg = f"No enrolled course found matching '{fragment}'"
            raise ValueError(msg)
        msg = _format_ambiguous(top, f"name fragment '{fragment}'")
        raise ValueError(msg)

    msg = f"No enrolled course found matching '{fragment}'"
    raise ValueError(msg)


async def _get_opencast_module(course: Course, moodle: MoodleAdapter) -> int:
    """Extract the Opencast module ID from a course's content."""
    sections = await moodle.get_course_content(course.id)
    for section in sections:
        for module in section.modules:
            if module.modname == "opencast":
                return module.id
    msg = f"No Opencast module found in course '{course.fullname}' (id={course.id})"
    raise ValueError(msg)


def _format_ambiguous(courses: list[Course], context: str) -> str:
    """Format an error message for ambiguous course matches."""
    lines = [f"Multiple courses match {context}:"]
    for c in courses:
        info = extract_course_info(c.shortname)
        number = info[0] if info else "?"
        lines.append(f"  - {number}: {c.fullname} (course_id={c.id})")
    lines.append("Please be more specific.")
    return "\n".join(lines)
