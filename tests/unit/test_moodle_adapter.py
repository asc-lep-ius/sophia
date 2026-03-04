"""Tests for the async Moodle adapter (session-based AJAX transport)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sophia.adapters.moodle import MoodleAdapter
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
WS_PATH = "/webservice/rest/server.php"
COURSE_VIEW_PATH = "/course/view.php"
SESSKEY = "test_sesskey_abc123"
MOODLE_SESSION = "test_session_cookie"
WS_TOKEN = "test_ws_token_abc123"

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


def _ws_ok(data: object) -> httpx.Response:
    """Build a successful WS REST response (data returned directly)."""
    return httpx.Response(200, json=data)


def _ws_error(errorcode: str, message: str) -> httpx.Response:
    """Build a WS REST error response."""
    return httpx.Response(
        200,
        json={
            "exception": "moodle_exception",
            "errorcode": errorcode,
            "message": message,
        },
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
        ws_token=WS_TOKEN,
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


class TestResourceProvider:
    @respx.mock
    async def test_get_course_books(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok({"books": [{"id": 1, "name": "Course Book", "url": None}]}),
        )
        books = await adapter.get_course_books([1])
        assert len(books) == 1
        assert isinstance(books[0], ModuleInfo)
        assert books[0].modname == "book"

    @respx.mock
    async def test_get_course_pages(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok({"pages": [{"id": 2, "name": "Info Page", "url": None}]}),
        )
        pages = await adapter.get_course_pages([1])
        assert len(pages) == 1
        assert pages[0].modname == "page"

    @respx.mock
    async def test_get_course_resources(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok({"resources": [{"id": 3, "name": "Slides.pdf", "url": None}]}),
        )
        resources = await adapter.get_course_resources([1])
        assert len(resources) == 1
        assert resources[0].modname == "resource"

    @respx.mock
    async def test_get_course_urls(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok(
                {"urls": [{"id": 4, "name": "External Link", "url": "https://example.com"}]}
            ),
        )
        urls = await adapter.get_course_urls([1])
        assert len(urls) == 1
        assert urls[0].modname == "url"
        assert urls[0].url == "https://example.com"


# ------------------------------------------------------------------
# AssignmentProvider
# ------------------------------------------------------------------


class TestGetAssignments:
    @respx.mock
    async def test_flattens_nested_response(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok(
                {
                    "courses": [
                        {
                            "id": 1,
                            "assignments": [
                                {"id": 10, "name": "HW1", "duedate": 1700000000},
                                {"id": 11, "name": "HW2", "duedate": 0},
                            ],
                        },
                        {
                            "id": 2,
                            "assignments": [
                                {"id": 20, "name": "Project", "duedate": 1700100000},
                            ],
                        },
                    ]
                }
            )
        )
        assignments = await adapter.get_assignments([1, 2])
        assert len(assignments) == 3
        assert all(isinstance(a, AssignmentInfo) for a in assignments)
        assert assignments[0].course_id == 1
        assert assignments[2].course_id == 2
        assert assignments[0].due_date == "1700000000"
        # duedate=0 → None
        assert assignments[1].due_date is None


class TestGetQuizzes:
    @respx.mock
    async def test_returns_quizzes(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok(
                {
                    "quizzes": [
                        {"id": 5, "name": "Midterm", "course": 1},
                        {"id": 6, "name": "Final", "course": 1},
                    ]
                }
            )
        )
        quizzes = await adapter.get_quizzes([1])
        assert len(quizzes) == 2
        assert all(isinstance(q, QuizInfo) for q in quizzes)
        assert quizzes[0].course_id == 1


class TestGetCheckmarks:
    @respx.mock
    async def test_returns_checkmarks(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok(
                {
                    "checkmarks": [
                        {"id": 7, "name": "Task 1", "course": 1, "completed": 1},
                        {"id": 8, "name": "Task 2", "course": 1, "completed": 0},
                    ]
                }
            )
        )
        checkmarks = await adapter.get_checkmarks([1])
        assert len(checkmarks) == 2
        assert all(isinstance(cm, CheckmarkInfo) for cm in checkmarks)
        assert checkmarks[0].completed is True
        assert checkmarks[1].completed is False


class TestGetGradeItems:
    @respx.mock
    async def test_returns_grade_items(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_ok(
                {
                    "usergrades": [
                        {
                            "gradeitems": [
                                {
                                    "id": 100,
                                    "itemname": "HW1",
                                    "graderaw": 85.0,
                                    "grademax": 100.0,
                                },
                                {
                                    "id": 101,
                                    "itemname": "HW2",
                                    "graderaw": None,
                                    "grademax": 50.0,
                                },
                            ]
                        }
                    ]
                }
            )
        )
        items = await adapter.get_grade_items(course_id=1)
        assert len(items) == 2
        assert all(isinstance(gi, GradeItem) for gi in items)
        assert items[0].grade == 85.0
        assert items[0].max_grade == 100.0
        assert items[1].grade is None

    @respx.mock
    async def test_empty_usergrades_returns_empty_list(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(return_value=_ws_ok({"usergrades": []}))
        items = await adapter.get_grade_items(course_id=99)
        assert items == []


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
    async def test_access_exception_raises_auth_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_error("accessexception", "Access control exception")
        )
        with pytest.raises(AuthError):
            await adapter.get_course_books([1])

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


# ------------------------------------------------------------------
# WS REST transport
# ------------------------------------------------------------------


class TestWsTransport:
    @respx.mock
    async def test_ws_error_raises_moodle_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_error("invalidrecord", "Can not find data record")
        )
        with pytest.raises(MoodleError, match="invalidrecord"):
            await adapter.get_course_books([1])

    @respx.mock
    async def test_ws_auth_error_raises_auth_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(
            return_value=_ws_error("accessexception", "Access denied")
        )
        with pytest.raises(AuthError):
            await adapter.get_course_books([1])

    async def test_missing_ws_token_raises_auth_error(self, client: httpx.AsyncClient):
        adapter_no_token = MoodleAdapter(
            http=client,
            sesskey=SESSKEY,
            moodle_session=MOODLE_SESSION,
            host=HOST,
        )
        with pytest.raises(AuthError, match="No WS token"):
            await adapter_no_token.get_course_books([1])

    @respx.mock
    async def test_array_params_flattened(self, adapter: MoodleAdapter):
        """Array params are sent as courseids[0]=1&courseids[1]=2."""
        route = respx.route(method="POST", path=WS_PATH).mock(return_value=_ws_ok({"books": []}))
        await adapter.get_course_books([10, 20])

        request = route.calls.last.request
        body = request.content.decode()
        assert "courseids%5B0%5D=10" in body or "courseids[0]=10" in body
        assert "courseids%5B1%5D=20" in body or "courseids[1]=20" in body

    @respx.mock
    async def test_ws_http_error_raises_moodle_error(self, adapter: MoodleAdapter):
        respx.route(method="POST", path=WS_PATH).mock(return_value=httpx.Response(502))
        with pytest.raises(MoodleError, match="502"):
            await adapter.get_course_books([1])
