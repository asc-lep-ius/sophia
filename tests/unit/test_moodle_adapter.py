"""Tests for the async Moodle adapter (session-based AJAX transport)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sophia.adapters.moodle import MoodleAdapter
from sophia.domain.errors import AuthError, MoodleError
from sophia.domain.models import (
    Course,
    CourseSection,
)
from sophia.domain.ports import AssignmentProvider, CourseProvider, ResourceProvider


# Structural conformance helper: verify the adapter has every method the protocol declares
def _conforms_to(instance: object, protocol: type) -> bool:
    """Check structural conformance without requiring @runtime_checkable."""
    hints = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    return all(callable(getattr(instance, name, None)) for name in hints)


HOST = "https://tuwel.tuwien.ac.at"
AJAX_PATH = "/lib/ajax/service.php"
COURSE_VIEW_PATH = "/course/view.php"
SESSKEY = "test_sesskey_abc123"
MOODLE_SESSION = "test_session_cookie"

COURSE_PAGE_HTML = """
<html><body>
<div class="course-content">
  <ul class="topics">
    <li class="section main clearfix" id="section-0">
      <div class="content">
        <h3 class="sectionname"><span>General</span></h3>
        <div class="summary">
          <p>Welcome to the course. Required reading: ISBN 978-0-13-468599-1</p>
        </div>
        <ul class="section img-text">
          <li class="activity resource modtype_resource" id="module-100">
            <div class="activityinstance">
              <a href="https://tuwel.tuwien.ac.at/mod/resource/view.php?id=100">
                <span class="instancename">Syllabus<span class="accesshide"> File</span></span>
              </a>
            </div>
          </li>
          <li class="activity book modtype_book" id="module-200">
            <div class="activityinstance">
              <a href="https://tuwel.tuwien.ac.at/mod/book/view.php?id=200">
                <span class="instancename">Course Textbook
                  <span class="accesshide"> Book</span>
                </span>
              </a>
            </div>
          </li>
        </ul>
      </div>
    </li>
    <li class="section main clearfix" id="section-1">
      <div class="content">
        <h3 class="sectionname"><span>Week 1: Introduction</span></h3>
        <div class="summary"><p>Recommended: Cormen et al., Introduction to Algorithms</p></div>
        <ul class="section img-text">
          <li class="activity page modtype_page" id="module-300">
            <div class="activityinstance">
              <a href="https://tuwel.tuwien.ac.at/mod/page/view.php?id=300">
                <span class="instancename">Reading List<span class="accesshide"> Page</span></span>
              </a>
            </div>
          </li>
          <li class="activity label modtype_label hasinfo" id="module-400">
            <div class="activity-item focus-control activityinline"
                 data-activityname="J. Kleinberg und E. Tardos..."
                 data-region="activity-card">
              <div class="activity-grid noname-grid">
                <div class="activity-altcontent text-break">
                  <div class="no-overflow">
                    <div class="no-overflow">
                      <ul>
                        <li>J. Kleinberg: <i>Algorithm Design</i>, Pearson, 2005</li>
                        <li>T. Ottmann: <i>Algorithmen und Datenstrukturen</i>, 2012</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </li>
  </ul>
</div>
</body></html>
"""


def _ajax_ok(data: object) -> httpx.Response:
    """Wrap data in a successful AJAX response."""
    return httpx.Response(200, json=[{"error": False, "data": data}])


def _ajax_error(errorcode: str, message: str) -> httpx.Response:
    """Build an AJAX error response."""
    return httpx.Response(
        200,
        json=[
            {
                "error": True,
                "exception": {"errorcode": errorcode, "message": message},
            }
        ],
    )


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


@pytest.fixture
def adapter(client: httpx.AsyncClient) -> MoodleAdapter:
    return MoodleAdapter(
        http=client,
        sesskey=SESSKEY,
        moodle_session=MOODLE_SESSION,
        host=HOST,
    )


# ------------------------------------------------------------------
# check_session
# ------------------------------------------------------------------


class TestCheckSession:
    @respx.mock
    async def test_valid_session(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_ok({"timeremaining": 7200, "userid": 1})
        )
        await adapter.check_session()

    @respx.mock
    async def test_expired_session_html_response(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Login</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(AuthError, match="Session expired"):
            await adapter.check_session()

    @respx.mock
    async def test_expired_session_error_response(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_error("servicerequireslogin", "You are not logged in")
        )
        with pytest.raises(AuthError):
            await adapter.check_session()

    @respx.mock
    async def test_function_unavailable_still_passes(self, adapter: MoodleAdapter):
        """Session is valid but function doesn't exist — should not raise."""
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_error("servicenotavailable", "Function not available")
        )
        await adapter.check_session()


# ------------------------------------------------------------------
# CourseProvider
# ------------------------------------------------------------------


class TestGetEnrolledCourses:
    @respx.mock
    async def test_returns_courses(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_ok(
                {
                    "courses": [
                        {
                            "id": 1,
                            "fullname": "Linear Algebra",
                            "shortname": "LA",
                            "viewurl": "https://tuwel.tuwien.ac.at/course/view.php?id=1",
                        },
                        {
                            "id": 2,
                            "fullname": "Analysis",
                            "shortname": "AN",
                        },
                    ],
                    "nextoffset": 0,
                }
            )
        )
        courses = await adapter.get_enrolled_courses()
        assert len(courses) == 2
        assert all(isinstance(c, Course) for c in courses)
        assert courses[0].id == 1
        assert courses[0].fullname == "Linear Algebra"
        assert courses[0].url == "https://tuwel.tuwien.ac.at/course/view.php?id=1"
        assert courses[1].url is None

    @respx.mock
    async def test_empty_courses(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_ok({"courses": [], "nextoffset": 0})
        )
        courses = await adapter.get_enrolled_courses()
        assert courses == []


class TestGetCourseContent:
    @respx.mock
    async def test_returns_sections(self, adapter: MoodleAdapter):
        respx.route(method="GET", path=COURSE_VIEW_PATH).mock(
            return_value=httpx.Response(200, text=COURSE_PAGE_HTML)
        )
        sections = await adapter.get_course_content(course_id=1)
        assert len(sections) == 2
        assert all(isinstance(s, CourseSection) for s in sections)
        assert sections[0].id == 0
        assert sections[0].name == "General"
        assert "ISBN 978-0-13-468599-1" in sections[0].summary
        assert sections[1].id == 1
        assert sections[1].name == "Week 1: Introduction"

    @respx.mock
    async def test_parses_modules(self, adapter: MoodleAdapter):
        respx.route(method="GET", path=COURSE_VIEW_PATH).mock(
            return_value=httpx.Response(200, text=COURSE_PAGE_HTML)
        )
        sections = await adapter.get_course_content(course_id=1)
        modules = sections[0].modules
        assert len(modules) == 2
        assert modules[0].id == 100
        assert modules[0].name == "Syllabus"
        assert modules[0].modname == "resource"
        assert modules[0].url == "https://tuwel.tuwien.ac.at/mod/resource/view.php?id=100"
        assert modules[1].id == 200
        assert modules[1].name == "Course Textbook"
        assert modules[1].modname == "book"

    @respx.mock
    async def test_parses_label_activity(self, adapter: MoodleAdapter):
        respx.route(method="GET", path=COURSE_VIEW_PATH).mock(
            return_value=httpx.Response(200, text=COURSE_PAGE_HTML)
        )
        sections = await adapter.get_course_content(course_id=1)
        week1_modules = sections[1].modules
        label = next(m for m in week1_modules if m.modname == "label")
        assert label.id == 400
        assert label.name == "J. Kleinberg und E. Tardos"
        # description preserves raw HTML so the reference extractor can parse tags
        assert "<li>" in label.description
        assert "<i>Algorithm Design</i>" in label.description
        assert "<i>Algorithmen und Datenstrukturen</i>" in label.description

    @respx.mock
    async def test_empty_course_page(self, adapter: MoodleAdapter):
        empty_html = "<html><body><div class='course-content'></div></body></html>"
        respx.route(method="GET", path=COURSE_VIEW_PATH).mock(
            return_value=httpx.Response(200, text=empty_html)
        )
        sections = await adapter.get_course_content(course_id=1)
        assert sections == []

    async def test_session_expired_redirects_to_login(self, adapter: MoodleAdapter):
        from unittest.mock import AsyncMock

        login_url = f"{HOST}/login/index.php"
        mock_resp = httpx.Response(
            200,
            text="<html>Login page</html>",
            request=httpx.Request("GET", login_url),
        )
        adapter._http = AsyncMock()  # noqa: SLF001
        adapter._http.get = AsyncMock(return_value=mock_resp)  # noqa: SLF001
        with pytest.raises(AuthError, match="Session expired"):
            await adapter.get_course_content(course_id=1)


# ------------------------------------------------------------------
# ResourceProvider
# ------------------------------------------------------------------


class TestNotImplementedMethods:
    """WS-dependent methods raise NotImplementedError until scraping replacements land."""

    async def test_get_course_books(self, adapter: MoodleAdapter):
        with pytest.raises(NotImplementedError, match="scraping replacement pending"):
            await adapter.get_course_books([1])

    async def test_get_assignments(self, adapter: MoodleAdapter):
        with pytest.raises(NotImplementedError, match="scraping replacement pending"):
            await adapter.get_assignments([1])

    async def test_get_quizzes(self, adapter: MoodleAdapter):
        with pytest.raises(NotImplementedError, match="scraping replacement pending"):
            await adapter.get_quizzes([1])

    async def test_get_grade_items(self, adapter: MoodleAdapter):
        with pytest.raises(NotImplementedError, match="scraping replacement pending"):
            await adapter.get_grade_items(1)


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


class TestErrorHandling:
    @respx.mock
    async def test_moodle_exception_raises_moodle_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_error("invalidrecord", "Can not find data record")
        )
        with pytest.raises(MoodleError, match="invalidrecord"):
            await adapter.get_enrolled_courses()

    @respx.mock
    async def test_invalid_session_raises_auth_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=_ajax_error("invalidsesskey", "Invalid session key")
        )
        with pytest.raises(AuthError):
            await adapter.get_enrolled_courses()

    @respx.mock
    async def test_http_error_raises_moodle_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=AJAX_PATH).mock(return_value=httpx.Response(502))
        with pytest.raises(MoodleError, match="502"):
            await adapter.get_enrolled_courses()

    @respx.mock
    async def test_html_response_raises_auth_error(self, adapter: MoodleAdapter):
        """HTML response (login page) means the session expired."""
        respx.route(method="POST", path=AJAX_PATH).mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Login</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(AuthError, match="Session expired"):
            await adapter.get_enrolled_courses()


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_course_provider(self, adapter: MoodleAdapter):
        assert _conforms_to(adapter, CourseProvider)

    def test_satisfies_resource_provider(self, adapter: MoodleAdapter):
        assert _conforms_to(adapter, ResourceProvider)

    def test_satisfies_assignment_provider(self, adapter: MoodleAdapter):
        assert _conforms_to(adapter, AssignmentProvider)
