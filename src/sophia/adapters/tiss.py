"""Async TISS adapter — public API client for course metadata and exam dates.

Fetches data from TISS's public XML API (no authentication required).
Implements CourseMetadataProvider protocol.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx
import structlog

from sophia.domain.errors import TissError
from sophia.domain.models import TissCourseInfo, TissExamDate

log = structlog.get_logger()

# Matches course number + semester from TUWEL shortnames like "186.866 ... 2026S"
_SHORTNAME_RE = re.compile(r"(\d{3}\.\d{3})\b.*\b(20\d{2}[SW])\b")

# XML namespace used in TISS API responses
_NS = {"tns": "http://www.tuwien.ac.at/2012/api/tiss"}


def clean_course_number(number: str) -> str:
    """Remove dots from a course number: '186.866' → '186866'."""
    return number.replace(".", "")


def extract_course_info(shortname: str) -> tuple[str, str] | None:
    """Extract (course_number, semester) from a TUWEL shortname.

    Example: '186.866 Algorithmen und Datenstrukturen 2026S' → ('186.866', '2026S')
    Returns None if the shortname doesn't match the expected pattern.
    """
    match = _SHORTNAME_RE.search(shortname)
    if not match:
        return None
    return match.group(1), match.group(2)


def _text(element: ET.Element, tag: str, lang: str = "") -> str:
    """Extract text from an XML element, optionally filtered by xml:lang attribute."""
    for child in element.iter(tag):
        if lang and child.get("{http://www.w3.org/XML/1998/namespace}lang") != lang:
            continue
        return (child.text or "").strip()
    # Also try with namespace
    for child in element.iter(f"{{{_NS['tns']}}}{tag}"):
        if lang and child.get("{http://www.w3.org/XML/1998/namespace}lang") != lang:
            continue
        return (child.text or "").strip()
    return ""


def parse_course_xml(xml_text: str) -> TissCourseInfo:
    """Parse TISS course details XML into a TissCourseInfo model."""
    root = ET.fromstring(xml_text)  # noqa: S314

    return TissCourseInfo(
        course_number=_text(root, "courseNumber"),
        semester=_text(root, "semester"),
        course_type=_text(root, "courseType"),
        title_de=_text(root, "title", lang="de"),
        title_en=_text(root, "title", lang="en"),
        ects=float(_text(root, "ects") or "0"),
        description_de=_text(root, "teachingContent", lang="de"),
        description_en=_text(root, "teachingContent", lang="en"),
        objectives_de=_text(root, "courseObjective", lang="de"),
        objectives_en=_text(root, "courseObjective", lang="en"),
    )


def parse_exam_dates_xml(xml_text: str, course_number: str) -> list[TissExamDate]:
    """Parse TISS exam dates XML into a list of TissExamDate models."""
    root = ET.fromstring(xml_text)  # noqa: S314

    results: list[TissExamDate] = []
    # Handle both namespaced and non-namespaced elements
    exam_elements = root.iter("examDate")
    for exam in exam_elements:
        results.append(
            TissExamDate(
                exam_id=_text(exam, "id"),
                course_number=course_number,
                title=_text(exam, "title"),
                date_start=_text(exam, "startDate") or None,
                date_end=_text(exam, "endDate") or None,
                registration_start=_text(exam, "registrationFrom") or None,
                registration_end=_text(exam, "registrationTo") or None,
                mode=_text(exam, "mode"),
            )
        )

    if not results:
        # Try with namespace prefix
        for exam in root.iter(f"{{{_NS['tns']}}}examDate"):
            results.append(
                TissExamDate(
                    exam_id=_text(exam, "id"),
                    course_number=course_number,
                    title=_text(exam, "title"),
                    date_start=_text(exam, "startDate") or None,
                    date_end=_text(exam, "endDate") or None,
                    registration_start=_text(exam, "registrationFrom") or None,
                    registration_end=_text(exam, "registrationTo") or None,
                    mode=_text(exam, "mode"),
                )
            )

    return results


class TissAdapter:
    """Async TISS public API client.

    Satisfies: CourseMetadataProvider protocol.
    """

    def __init__(self, http: httpx.AsyncClient, host: str) -> None:
        self._http = http
        self._host = host.rstrip("/")
        self._api_base = f"{self._host}/api"

    async def get_course_details(self, course_number: str, semester: str) -> TissCourseInfo:
        """Fetch course details from TISS public API."""
        clean_number = clean_course_number(course_number)
        url = f"{self._api_base}/course/{clean_number}-{semester}"

        log.debug("tiss.get_course_details", url=url, course=course_number, semester=semester)

        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise TissError(f"TISS API request failed for course {course_number}") from exc

        if response.status_code == 404:
            log.warning("tiss.course_not_found", course=course_number, semester=semester)
            return TissCourseInfo(course_number=course_number, semester=semester)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TissError(
                f"HTTP {exc.response.status_code} from TISS API for course {course_number}"
            ) from exc

        try:
            return parse_course_xml(response.text)
        except ET.ParseError as exc:
            raise TissError(f"Failed to parse TISS XML for course {course_number}") from exc

    async def get_exam_dates(self, course_number: str) -> list[TissExamDate]:
        """Fetch exam dates from TISS public API."""
        clean_number = clean_course_number(course_number)
        url = f"{self._api_base}/course/{clean_number}/examDates"

        log.debug("tiss.get_exam_dates", url=url, course=course_number)

        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise TissError(
                f"TISS API request failed for exam dates of course {course_number}"
            ) from exc

        if response.status_code == 404:
            log.warning("tiss.exam_dates_not_found", course=course_number)
            return []

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TissError(
                f"HTTP {exc.response.status_code} from TISS API for exam dates of {course_number}"
            ) from exc

        try:
            return parse_exam_dates_xml(response.text, course_number)
        except ET.ParseError as exc:
            raise TissError(
                f"Failed to parse TISS exam dates XML for course {course_number}"
            ) from exc
