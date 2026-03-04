"""Async Moodle adapter — session-based AJAX transport.

Implements CourseProvider, ResourceProvider, AssignmentProvider via
Moodle's AJAX service endpoint (lib/ajax/service.php) using browser
session cookies instead of WS tokens.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

import httpx
import structlog
from bs4 import BeautifulSoup, Tag

from sophia.domain.errors import AuthError, MoodleError
from sophia.domain.models import (
    AssignmentInfo,
    CheckmarkInfo,
    Course,
    CourseSection,
    GradeItem,
    ModuleInfo,
    QuizInfo,
)

log = structlog.get_logger()

# Error codes indicating an expired or invalid session
_AUTH_ERROR_CODES = frozenset(
    {
        "accessexception",
        "invalidsesskey",
        "requirelogin",
        "servicerequireslogin",
        "requireloginerror",
        "forcepasswordchangenotice",
        "usernotfullysetup",
    }
)


class MoodleAdapter:
    """Async Moodle adapter using session-based AJAX API.

    Satisfies: CourseProvider, ResourceProvider, AssignmentProvider protocols.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        sesskey: str,
        moodle_session: str,
        host: str,
        cookie_name: str = "MoodleSession",
    ) -> None:
        self._http = http
        self._sesskey = sesskey
        self._moodle_session = moodle_session
        self._cookie_name = cookie_name
        self._host = host.rstrip("/")
        self._ajax_endpoint = f"{self._host}/lib/ajax/service.php"

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    async def _call(self, function: str, params: dict[str, Any] | None = None) -> Any:
        """POST to the Moodle AJAX API and return parsed JSON.

        Uses lib/ajax/service.php with session cookie authentication.
        Raises MoodleError for Moodle-level errors and AuthError for session issues.
        """
        payload = [{"index": 0, "methodname": function, "args": params or {}}]

        response = await self._http.post(
            self._ajax_endpoint,
            params={"sesskey": self._sesskey, "info": function},
            json=payload,
            cookies={self._cookie_name: self._moodle_session},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleError(f"HTTP {exc.response.status_code} from Moodle AJAX API") from exc

        # HTML response means session expired (login page returned)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise AuthError("Session expired — log in again with: sophia auth login")

        body = response.json()

        if not isinstance(body, list) or len(body) == 0:
            raise MoodleError(f"Unexpected AJAX response format: {body}")

        result = body[0]
        if result.get("error"):
            exception = result.get("exception", {})
            errorcode = exception.get("errorcode", "")
            message = exception.get("message", str(result))
            if errorcode in _AUTH_ERROR_CODES:
                raise AuthError(message)
            raise MoodleError(f"[{errorcode}] {message}")

        return result["data"]

    # ------------------------------------------------------------------
    # Session validation
    # ------------------------------------------------------------------

    async def check_session(self) -> None:
        """Fail-fast session validation — call before expensive operations.

        Makes a lightweight AJAX call. If the session is expired, _call raises
        AuthError (via HTML detection or auth error codes). If the function
        doesn't exist but the session is valid, the MoodleError is ignored.
        """
        with contextlib.suppress(MoodleError):
            await self._call("core_session_time_remaining")

    # ------------------------------------------------------------------
    # CourseProvider
    # ------------------------------------------------------------------

    async def get_enrolled_courses(self, classification: str = "inprogress") -> list[Course]:
        data = await self._call(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"classification": classification, "limit": 0},
        )
        return [
            Course(
                id=c["id"],
                fullname=c["fullname"],
                shortname=c["shortname"],
                url=c.get("viewurl"),
            )
            for c in data["courses"]
        ]

    async def get_course_content(self, course_id: int) -> list[CourseSection]:
        """Fetch course content by scraping the course page HTML.

        The AJAX API doesn't whitelist core_course_get_contents on all
        Moodle instances, and WS tokens may not be available.  Scraping
        the course page with the session cookie is universally reliable.
        """
        url = f"{self._host}/course/view.php"
        response = await self._http.get(
            url,
            params={"id": course_id},
            cookies={self._cookie_name: self._moodle_session},
        )
        if "login" in str(response.url) and response.status_code in (200, 302):
            raise AuthError("Session expired \u2014 log in again with: sophia auth login")
        response.raise_for_status()
        return _parse_course_page(response.text)

    # ------------------------------------------------------------------
    # ResourceProvider
    # ------------------------------------------------------------------

    async def get_course_books(self, course_ids: list[int]) -> list[ModuleInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    # ------------------------------------------------------------------
    # AssignmentProvider
    # ------------------------------------------------------------------

    async def get_assignments(self, course_ids: list[int]) -> list[AssignmentInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_quizzes(self, course_ids: list[int]) -> list[QuizInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_checkmarks(self, course_ids: list[int]) -> list[CheckmarkInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_grade_items(self, course_id: int) -> list[GradeItem]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")


# ------------------------------------------------------------------
# HTML scraping helpers
# ------------------------------------------------------------------


def _parse_course_page(html: str) -> list[CourseSection]:
    """Parse Moodle course-page HTML into ``CourseSection`` objects."""
    soup = BeautifulSoup(html, "lxml")
    sections: list[CourseSection] = []

    for section_el in soup.select("li.section[id^='section-']"):
        section_id_str = section_el.get("id", "section-0")
        section_id = _extract_trailing_int(str(section_id_str), default=0)

        name_el = section_el.select_one("h3.sectionname")
        name = name_el.get_text(strip=True) if name_el else ""

        summary_el = section_el.select_one("div.summary")
        summary = summary_el.decode_contents().strip() if summary_el else ""

        modules = [
            mod
            for act in section_el.select("li.activity")
            if (mod := _parse_activity_element(act)) is not None
        ]

        sections.append(CourseSection(id=section_id, name=name, summary=summary, modules=modules))

    return sections


def _parse_activity_element(el: Tag) -> ModuleInfo | None:
    """Parse a single ``li.activity`` element into a `ModuleInfo`."""
    el_id = str(el.get("id", ""))
    match = re.match(r"module-(\d+)", el_id)
    if not match:
        return None
    module_id = int(match.group(1))

    modname = ""
    for cls in el.get("class", []):
        if cls.startswith("modtype_"):
            modname = cls[len("modtype_") :]
            break

    link = el.select_one("div.activityinstance a")
    url: str | None = link["href"] if link and link.get("href") else None  # type: ignore[assignment]

    name_el = el.select_one("span.instancename")
    if name_el:
        # Remove accesshide spans before extracting visible text
        for hidden in name_el.select("span.accesshide"):
            hidden.decompose()
        name = name_el.get_text(strip=True)
    else:
        # Labels lack span.instancename; fall back to data-activityname
        item_div = el.select_one("div.activity-item[data-activityname]")
        raw_name = item_div["data-activityname"] if item_div else ""  # type: ignore[index]
        name = str(raw_name).strip().rstrip(".")

    description = ""
    alt_content = el.select_one("div.activity-altcontent")
    if alt_content:
        description = alt_content.decode_contents().strip()

    return ModuleInfo(id=module_id, name=name, modname=modname, url=url, description=description)


def _extract_trailing_int(value: str, *, default: int = 0) -> int:
    """Extract the integer after the last hyphen (e.g. 'section-3' → 3)."""
    parts = value.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return default
