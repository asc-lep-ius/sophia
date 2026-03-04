"""Async Moodle adapter — session-based AJAX transport.

Implements CourseProvider, ResourceProvider, AssignmentProvider via
Moodle's AJAX service endpoint (lib/ajax/service.php) using browser
session cookies instead of WS tokens.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any, cast

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
        ws_token: str | None = None,
    ) -> None:
        self._http = http
        self._sesskey = sesskey
        self._moodle_session = moodle_session
        self._cookie_name = cookie_name
        self._host = host.rstrip("/")
        self._ajax_endpoint = f"{self._host}/lib/ajax/service.php"
        self._ws_token = ws_token

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

    async def _call_ws(self, function: str, params: dict[str, Any] | None = None) -> Any:
        """POST to the Moodle WS REST API and return parsed JSON.

        Uses webservice/rest/server.php with WS token authentication.
        Raises AuthError if no WS token is available.
        """
        if self._ws_token is None:
            raise AuthError("No WS token \u2014 re-login required")

        data: dict[str, str] = {
            "wstoken": self._ws_token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
        }
        if params:
            data.update(_flatten_params(params))

        response = await self._http.post(
            f"{self._host}/webservice/rest/server.php",
            data=data,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleError(f"HTTP {exc.response.status_code} from Moodle WS API") from exc

        body: Any = response.json()

        if isinstance(body, dict) and "exception" in body:
            err = cast("dict[str, str]", body)
            errorcode = err.get("errorcode", "")
            message = err.get("message", str(err))
            if errorcode in _AUTH_ERROR_CODES:
                raise AuthError(message)
            raise MoodleError(f"[{errorcode}] {message}")

        return body  # type: ignore[reportUnknownVariableType]

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
        data = await self._call_ws("mod_book_get_books_by_courses", {"courseids": course_ids})
        return [_parse_module(b, modname="book") for b in data["books"]]

    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call_ws("mod_page_get_pages_by_courses", {"courseids": course_ids})
        return [_parse_module(p, modname="page") for p in data["pages"]]

    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call_ws(
            "mod_resource_get_resources_by_courses", {"courseids": course_ids}
        )
        return [_parse_module(r, modname="resource") for r in data["resources"]]

    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call_ws("mod_url_get_urls_by_courses", {"courseids": course_ids})
        return [_parse_module(u, modname="url") for u in data["urls"]]

    # ------------------------------------------------------------------
    # AssignmentProvider
    # ------------------------------------------------------------------

    async def get_assignments(self, course_ids: list[int]) -> list[AssignmentInfo]:
        data = await self._call_ws("mod_assign_get_assignments", {"courseids": course_ids})
        return [
            AssignmentInfo(
                id=a["id"],
                name=a["name"],
                course_id=c["id"],
                due_date=str(a["duedate"]) if a.get("duedate") else None,
            )
            for c in data["courses"]
            for a in c["assignments"]
        ]

    async def get_quizzes(self, course_ids: list[int]) -> list[QuizInfo]:
        data = await self._call_ws("mod_quiz_get_quizzes_by_courses", {"courseids": course_ids})
        return [
            QuizInfo(id=q["id"], name=q["name"], course_id=q["course"]) for q in data["quizzes"]
        ]

    async def get_checkmarks(self, course_ids: list[int]) -> list[CheckmarkInfo]:
        data = await self._call_ws(
            "mod_checkmark_get_checkmarks_by_courses", {"courseids": course_ids}
        )
        return [
            CheckmarkInfo(
                id=cm["id"],
                name=cm["name"],
                course_id=cm["course"],
                completed=bool(cm.get("completed", False)),
            )
            for cm in data["checkmarks"]
        ]

    async def get_grade_items(self, course_id: int) -> list[GradeItem]:
        data = await self._call_ws("gradereport_user_get_grade_items", {"courseid": course_id})
        user_grades = data.get("usergrades", [])
        if not user_grades:
            return []
        return [
            GradeItem(
                id=gi["id"],
                name=gi.get("itemname", ""),
                grade=gi.get("graderaw"),
                max_grade=gi.get("grademax"),
            )
            for gi in user_grades[0]["gradeitems"]
        ]


# ------------------------------------------------------------------
# Parameter encoding
# ------------------------------------------------------------------


def _flatten_params(params: dict[str, Any]) -> dict[str, str]:
    """Flatten list values into Moodle's indexed parameter format.

    Converts ``{"courseids": [1, 2]}`` → ``{"courseids[0]": "1", "courseids[1]": "2"}``.
    """
    flat: dict[str, str] = {}
    for key, val in params.items():
        if isinstance(val, list):
            for i, item in enumerate(cast("list[Any]", val)):
                flat[f"{key}[{i}]"] = str(item)
        else:
            flat[key] = str(val)
    return flat


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


# ------------------------------------------------------------------
# Response-parsing helpers (WS REST API)
# ------------------------------------------------------------------


def _parse_module(raw: dict[str, Any], *, modname: str) -> ModuleInfo:
    """Parse a flat resource/book/page/url response into ModuleInfo."""
    return ModuleInfo(
        id=raw["id"],
        name=raw["name"],
        modname=modname,
        url=raw.get("url"),
    )
