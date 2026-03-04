"""Async Moodle adapter — session-based AJAX transport.

Implements CourseProvider, ResourceProvider, AssignmentProvider via
Moodle's AJAX service endpoint (lib/ajax/service.php) using browser
session cookies instead of WS tokens.
"""

from __future__ import annotations

import contextlib
from typing import Any

import httpx
import structlog

from sophia.domain.errors import AuthError, MoodleError
from sophia.domain.models import (
    AssignmentInfo,
    CheckmarkInfo,
    ContentInfo,
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
        sections = await self._call("core_course_get_contents", {"courseid": course_id})
        return [_parse_section(s) for s in sections]

    # ------------------------------------------------------------------
    # ResourceProvider
    # ------------------------------------------------------------------

    async def get_course_books(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call("mod_book_get_books_by_courses", {"courseids": course_ids})
        return [_parse_module(b, modname="book") for b in data["books"]]

    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call("mod_page_get_pages_by_courses", {"courseids": course_ids})
        return [_parse_module(p, modname="page") for p in data["pages"]]

    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call(
            "mod_resource_get_resources_by_courses", {"courseids": course_ids}
        )
        return [_parse_module(r, modname="resource") for r in data["resources"]]

    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call("mod_url_get_urls_by_courses", {"courseids": course_ids})
        return [_parse_module(u, modname="url") for u in data["urls"]]

    # ------------------------------------------------------------------
    # AssignmentProvider
    # ------------------------------------------------------------------

    async def get_assignments(self, course_ids: list[int]) -> list[AssignmentInfo]:
        data = await self._call("mod_assign_get_assignments", {"courseids": course_ids})
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
        data = await self._call("mod_quiz_get_quizzes_by_courses", {"courseids": course_ids})
        return [
            QuizInfo(id=q["id"], name=q["name"], course_id=q["course"]) for q in data["quizzes"]
        ]

    async def get_checkmarks(self, course_ids: list[int]) -> list[CheckmarkInfo]:
        data = await self._call(
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
        data = await self._call("gradereport_user_get_grade_items", {"courseid": course_id})
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
# Response-parsing helpers
# ------------------------------------------------------------------


def _parse_section(raw: dict[str, Any]) -> CourseSection:
    return CourseSection(
        id=raw["id"],
        name=raw["name"],
        summary=raw.get("summary", ""),
        modules=[_parse_section_module(m) for m in raw.get("modules", [])],
    )


def _parse_section_module(raw: dict[str, Any]) -> ModuleInfo:
    return ModuleInfo(
        id=raw["id"],
        name=raw["name"],
        modname=raw.get("modname", ""),
        url=raw.get("url"),
        contents=[
            ContentInfo(
                filename=c["filename"],
                fileurl=c["fileurl"],
                filesize=c.get("filesize", 0),
                mimetype=c.get("mimetype", ""),
            )
            for c in raw.get("contents", [])
        ],
    )


def _parse_module(raw: dict[str, Any], *, modname: str) -> ModuleInfo:
    """Parse a flat resource/book/page/url response into ModuleInfo."""
    return ModuleInfo(
        id=raw["id"],
        name=raw["name"],
        modname=modname,
        url=raw.get("url"),
    )
