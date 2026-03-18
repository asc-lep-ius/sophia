"""Async Moodle adapter — session-based AJAX transport.

Implements CourseProvider, ResourceProvider, AssignmentProvider via
Moodle's AJAX service endpoint (lib/ajax/service.php) using browser
session cookies instead of WS tokens.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup, Tag

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

try:
    import fitz  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]
except ImportError:  # pragma: no cover - optional dependency
    fitz = None

log = structlog.get_logger()

_MAX_INGESTION_CHARS = 20_000
_MAX_PDF_PAGES = 5
_MAX_PDF_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
_ENRICHMENT_TIMEOUT_S = 60
_URL_CONTENT_SELECTORS = (
    ".urlworkaround",
    "#region-main",
    "main",
    ".activity-description",
    ".box.generalbox",
)
_MOODLE_INTERNAL_PATH_PREFIXES = (
    "/admin/",
    "/badges/",
    "/blog/",
    "/calendar/",
    "/comment/",
    "/competency/",
    "/course/",
    "/enrol/",
    "/files/",
    "/grade/",
    "/group/",
    "/lib/",
    "/local/",
    "/login/",
    "/message/",
    "/mod/",
    "/my/",
    "/notes/",
    "/question/",
    "/report/",
    "/theme/",
    "/user/",
)

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


async def _gather_enrichments(
    tasks: list[asyncio.Task[ModuleInfo]],
    originals: list[ModuleInfo],
    kind: str,
) -> list[ModuleInfo]:
    """Run enrichment tasks with a timeout, returning partial results on failure.

    Each task corresponds positionally to an original module. On timeout or
    exception the original module is returned as-is, so enrichment never blocks
    or loses data.
    """
    done, pending = await asyncio.wait(tasks, timeout=_ENRICHMENT_TIMEOUT_S)
    if pending:
        for task in pending:
            task.cancel()
        log.warning("enrichment_timeout", kind=kind, timed_out=len(pending), completed=len(done))

    # Build index of completed tasks → results
    task_results: dict[int, ModuleInfo] = {}
    for i, task in enumerate(tasks):
        if task in done:
            exc = task.exception()
            if exc is not None:
                log.warning(
                    "enrichment_failed",
                    kind=kind,
                    module_id=originals[i].id,
                    error=str(exc),
                )
            else:
                task_results[i] = task.result()

    return [task_results.get(i, originals[i]) for i in range(len(originals))]


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

    @property
    def moodle_session(self) -> str:
        return self._moodle_session

    @property
    def cookie_name(self) -> str:
        return self._cookie_name

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
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleError(f"HTTP {exc.response.status_code} from Moodle AJAX API") from exc

        # HTML response means session expired (login page returned)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise AuthError("Session expired — log in again with: sophia auth login")

        raw_body: Any = response.json()

        if not isinstance(raw_body, list) or not raw_body:
            raise MoodleError(f"Unexpected AJAX response format: {raw_body}")

        result = cast("dict[str, Any]", raw_body[0])
        if result.get("error"):
            exception = cast("dict[str, Any]", result.get("exception", {}))
            errorcode = str(exception.get("errorcode", ""))
            message = str(exception.get("message", str(result)))
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

    async def _scrape(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Fetch a Moodle page via GET and return raw HTML.

        Checks for login redirect (session expired) and raises AuthError.
        """
        url = f"{self._host}{path}"
        response = await self._http.get(
            url,
            params=params or {},
        )
        if "login" in str(response.url) and response.status_code in (200, 302):
            raise AuthError("Session expired — log in again with: sophia auth login")
        response.raise_for_status()
        return response.text

    async def get_course_content(self, course_id: int) -> list[CourseSection]:
        """Fetch course content by scraping the course page HTML.

        The AJAX API doesn't whitelist core_course_get_contents on all
        Moodle instances, and WS tokens may not be available.  Scraping
        the course page with the session cookie is universally reliable.
        """
        html = await self._scrape("/course/view.php", {"id": course_id})
        return _parse_course_page(html)

    # ------------------------------------------------------------------
    # ResourceProvider
    # ------------------------------------------------------------------

    async def get_course_books(self, course_ids: list[int]) -> list[ModuleInfo]:
        results: list[ModuleInfo] = []
        for cid in course_ids:
            html = await self._scrape("/mod/book/index.php", {"id": cid})
            results.extend(_parse_mod_index(html, modname="book"))
        return results

    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]:
        results: list[ModuleInfo] = []
        for cid in course_ids:
            html = await self._scrape("/mod/page/index.php", {"id": cid})
            results.extend(_parse_mod_index(html, modname="page"))
        return results

    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]:
        results: list[ModuleInfo] = []
        for cid in course_ids:
            html = await self._scrape("/mod/resource/index.php", {"id": cid})
            modules = _parse_mod_index(html, modname="resource")
            results.extend(await self._enrich_resource_modules(modules))
        return results

    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]:
        results: list[ModuleInfo] = []
        for cid in course_ids:
            html = await self._scrape("/mod/url/index.php", {"id": cid})
            modules = _parse_mod_index(html, modname="url")
            results.extend(await self._enrich_url_modules(modules))
        return results

    async def _enrich_resource_modules(self, modules: list[ModuleInfo]) -> list[ModuleInfo]:
        if not modules:
            return []
        tasks = [asyncio.ensure_future(self._enrich_resource_module(m)) for m in modules]
        result = await _gather_enrichments(tasks, modules, "resource")
        enriched = sum(
            1 for original, updated in zip(modules, result, strict=True) if updated is not original
        )
        log.info(
            "resource_enrichment_complete",
            total=len(modules),
            enriched=enriched,
            skipped=len(modules) - enriched,
        )
        return result

    async def _enrich_url_modules(self, modules: list[ModuleInfo]) -> list[ModuleInfo]:
        if not modules:
            return []
        tasks = [asyncio.ensure_future(self._enrich_url_module(m)) for m in modules]
        result = await _gather_enrichments(tasks, modules, "url")
        enriched = sum(
            1 for original, updated in zip(modules, result, strict=True) if updated is not original
        )
        log.info(
            "url_enrichment_complete",
            total=len(modules),
            enriched=enriched,
            skipped=len(modules) - enriched,
        )
        return result

    async def _enrich_url_module(self, module: ModuleInfo) -> ModuleInfo:
        if not module.url:
            return module

        try:
            response = await self._fetch(module.url)
            target_url, target_response = await self._resolve_url_target(module.url, response)
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("url_module_enrichment_skipped", module_id=module.id, error=str(exc))
            return module

        if not target_url:
            return module

        description = module.description
        if target_response is not None:
            text = _extract_response_text(target_response)
            if text:
                description = _merge_description(description, text)

        return module.model_copy(
            update={
                "description": description,
                "contents": [_build_content_info(target_url, target_response)],
            }
        )

    async def _enrich_resource_module(self, module: ModuleInfo) -> ModuleInfo:
        if not module.url:
            return module

        try:
            response = await self._fetch(module.url)
            file_url, file_response = await self._resolve_resource_target(module.url, response)
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("resource_module_enrichment_skipped", module_id=module.id, error=str(exc))
            return module

        if not file_url:
            return module

        description = module.description
        if file_response is not None and _response_is_pdf(file_response, file_url):
            if len(file_response.content) > _MAX_PDF_SIZE_BYTES:
                log.warning(
                    "pdf_too_large_skipping",
                    module_id=module.id,
                    size=len(file_response.content),
                    limit=_MAX_PDF_SIZE_BYTES,
                )
            else:
                pdf_text = _extract_pdf_text(file_response.content)
                if pdf_text:
                    description = _merge_description(description, pdf_text)

        return module.model_copy(
            update={
                "description": description,
                "contents": [_build_content_info(file_url, file_response)],
            }
        )

    async def _fetch(self, url: str) -> httpx.Response:
        response = await self._http.get(url, follow_redirects=True)
        if _is_login_url(str(response.url), self._host) and response.status_code in (200, 302):
            raise AuthError("Session expired — log in again with: sophia auth login")
        response.raise_for_status()
        return response

    async def _resolve_url_target(
        self,
        module_url: str,
        response: httpx.Response,
    ) -> tuple[str | None, httpx.Response | None]:
        resolved_url = str(response.url)
        if _is_http_url(resolved_url) and resolved_url != module_url:
            return resolved_url, response

        if not _response_is_html(response):
            return None, None

        outbound_url = _extract_outbound_url(response.text, base_url=resolved_url, host=self._host)
        if not outbound_url:
            return None, None

        try:
            target_response = await self._fetch(outbound_url)
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("url_target_fetch_skipped", module_url=module_url, error=str(exc))
            return outbound_url, None

        return str(target_response.url), target_response

    async def _resolve_resource_target(
        self,
        module_url: str,
        response: httpx.Response,
    ) -> tuple[str | None, httpx.Response | None]:
        resolved_url = str(response.url)
        if _looks_like_download(resolved_url, response):
            return resolved_url, response

        if not _response_is_html(response):
            return resolved_url, response

        resource_url = _extract_resource_url(response.text, base_url=resolved_url)
        if not resource_url:
            return None, None

        try:
            resource_response = await self._fetch(resource_url)
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("resource_target_fetch_skipped", module_url=module_url, error=str(exc))
            return resource_url, None

        return str(resource_response.url), resource_response

    # ------------------------------------------------------------------
    # AssignmentProvider
    # ------------------------------------------------------------------

    async def get_assignments(self, course_ids: list[int]) -> list[AssignmentInfo]:
        results: list[AssignmentInfo] = []
        for cid in course_ids:
            html = await self._scrape("/mod/assign/index.php", {"id": cid})
            results.extend(_parse_assignment_index(html, cid))
        return results

    async def get_quizzes(self, course_ids: list[int]) -> list[QuizInfo]:
        raise NotImplementedError("WS transport removed; scraping replacement pending")

    async def get_checkmarks(self, course_ids: list[int]) -> list[CheckmarkInfo]:
        results: list[CheckmarkInfo] = []
        for cid in course_ids:
            grade_items = await self.get_grade_items(cid)
            for item in grade_items:
                if item.item_type.lower() != "checkmark":
                    continue
                has_grade = item.grade is not None and item.grade not in ("", "-")
                results.append(
                    CheckmarkInfo(
                        id=item.id,
                        name=item.name,
                        course_id=cid,
                        grade=item.grade,
                        max_grade=item.max_grade,
                        completed=has_grade,
                        url=item.url,
                    )
                )
        return results

    async def get_grade_items(self, course_id: int) -> list[GradeItem]:
        html = await self._scrape("/grade/report/user/index.php", {"id": course_id})
        return _parse_grade_report(html)


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
    raw_classes = el.get("class")
    classes: list[str] = raw_classes if isinstance(raw_classes, list) else []
    for cls in classes:
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


def _extract_id_from_row(row_id: str) -> int:
    """Extract the numeric ID from a grade-row id like 'row_684001_231105'."""
    match = re.match(r"row_(\d+)_", row_id)
    return int(match.group(1)) if match else 0


def _extract_range_max(range_text: str) -> str | None:
    """Extract max value from range like '0–6' or '0-6'."""
    # Handles both en-dash (U+2013) and regular hyphen
    parts = re.split(r"[–\-]", range_text.strip())
    if len(parts) == 2 and parts[1].strip():
        return parts[1].strip()
    return None


def _parse_grade_report(html: str) -> list[GradeItem]:
    """Parse TUWEL grade report HTML into ``GradeItem`` objects."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.generaltable.user-grade")
    if not table:
        return []

    items: list[GradeItem] = []
    current_category = ""

    for row in table.select("tbody > tr"):
        th = row.select_one("th")
        if not th:
            continue

        # Category rows update the current category context
        if "category" in (th.get("class") or []):
            cat_span = th.select_one("div.category-content span:not(.collapsed):not(.expanded)")
            if cat_span:
                current_category = cat_span.get_text(strip=True)
            continue

        # Only process item rows (th with "item" class)
        th_classes = list(th.get("class") or [])
        if "item" not in th_classes:
            continue

        row_id = str(th.get("id", ""))
        item_id = _extract_id_from_row(row_id)

        # Item type from the uppercase label
        type_el = th.select_one("span.d-block.text-uppercase")
        item_type = type_el.get_text(strip=True) if type_el else ""

        # Name from .rowtitle
        name_el = th.select_one(".rowtitle")
        name = name_el.get_text(strip=True) if name_el else ""

        # URL from link
        link_el = th.select_one("a.gradeitemheader[href]")
        url: str | None = str(link_el["href"]) if link_el else None

        # Grade — must strip action menu before extracting text
        grade_el = row.select_one("td.column-grade")
        grade: str | None = None
        if grade_el:
            for menu in grade_el.select("div.action-menu"):
                menu.decompose()
            grade_text = grade_el.get_text(strip=True)
            grade = None if grade_text in ("", "-") else grade_text

        # Range → max_grade
        range_el = row.select_one("td.column-range")
        range_text = range_el.get_text(strip=True) if range_el else ""
        max_grade = _extract_range_max(range_text) if range_text else None

        # Weight (may not exist in 4-column layouts)
        weight_el = row.select_one("td.column-weight")
        weight_text = weight_el.get_text(strip=True) if weight_el else None
        weight = None if weight_text in (None, "", "-") else weight_text

        # Percentage (may not exist)
        pct_el = row.select_one("td.column-percentage")
        pct_text = pct_el.get_text(strip=True) if pct_el else None
        percentage = None if pct_text in (None, "", "-") else pct_text

        # Feedback
        fb_el = row.select_one("td.column-feedback")
        feedback = fb_el.get_text(strip=True) if fb_el else ""

        items.append(
            GradeItem(
                id=item_id,
                name=name,
                item_type=item_type,
                grade=grade,
                max_grade=max_grade,
                weight=weight,
                percentage=percentage,
                feedback=feedback,
                url=url,
                category=current_category,
            )
        )

    return items


def _parse_mod_index(html: str, *, modname: str) -> list[ModuleInfo]:
    """Parse a Moodle mod/*/index.php page into ModuleInfo objects.

    TUWEL uses the same ``course-overview-table`` layout for all module
    index pages (books, pages, resources, URLs, assignments).  Each row
    carries its cmid in ``data-mdl-overview-cmid`` and the activity name
    in ``td[data-mdl-overview-item='name']``.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.course-overview-table")
    if not table:
        return []
    modules: list[ModuleInfo] = []
    for row in table.select("tbody > tr[data-mdl-overview-cmid]"):
        cmid = int(row["data-mdl-overview-cmid"])  # type: ignore[arg-type]
        name_td = row.select_one("td[data-mdl-overview-item='name']")
        name = str(name_td.get("data-mdl-overview-value", "")) if name_td else ""
        link = row.select_one("a.activityname[href]")
        url: str | None = str(link["href"]) if link else None
        modules.append(ModuleInfo(id=cmid, name=name, modname=modname, url=url))
    return modules


def _parse_assignment_index(html: str, course_id: int) -> list[AssignmentInfo]:
    """Parse TUWEL assignment index HTML into ``AssignmentInfo`` objects."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.course-overview-table")
    if not table:
        return []

    assignments: list[AssignmentInfo] = []

    for row in table.select("tbody > tr[data-mdl-overview-cmid]"):
        cmid = int(row["data-mdl-overview-cmid"])  # type: ignore[arg-type]

        name_td = row.select_one("td[data-mdl-overview-item='name']")
        name = str(name_td.get("data-mdl-overview-value", "")) if name_td else ""

        due_td = row.select_one("td[data-mdl-overview-item='duedate']")
        due_val = str(due_td.get("data-mdl-overview-value", "")) if due_td else ""
        due_date = due_val if due_val else None

        status_td = row.select_one("td[data-mdl-overview-item='submissionstatus']")
        submission_status = str(status_td.get("data-mdl-overview-value", "")) if status_td else ""

        grade_td = row.select_one("td[data-mdl-overview-item='Grade']")
        grade_val = str(grade_td.get("data-mdl-overview-value", "")) if grade_td else ""
        grade = None if grade_val in ("", "-") else grade_val

        link = row.select_one("a.activityname[href]")
        url: str | None = str(link["href"]) if link else None

        row_classes = list(row.get("class") or [])
        is_restricted = "bg-danger-subtle" in row_classes

        assignments.append(
            AssignmentInfo(
                id=cmid,
                name=name,
                course_id=course_id,
                due_date=due_date,
                submission_status=submission_status,
                grade=grade,
                url=url,
                is_restricted=is_restricted,
            )
        )

    return assignments


def _extract_outbound_url(html: str, *, base_url: str, host: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    host_name = urlparse(host).hostname or ""
    seen: set[str] = set()

    containers = [
        container for selector in _URL_CONTENT_SELECTORS for container in soup.select(selector)
    ]

    if not containers:
        containers = [soup]

    for container in containers:
        for anchor in container.select("a[href]"):
            href = urljoin(base_url, str(anchor["href"]))
            if href in seen or not _is_http_url(href):
                continue
            seen.add(href)

            parsed = urlparse(href)
            if parsed.hostname == host_name and _is_moodle_internal_path(parsed.path):
                continue
            return href

    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, str(anchor["href"]))
        if href in seen or not _is_http_url(href):
            continue

        parsed = urlparse(href)
        if parsed.hostname == host_name and _is_moodle_internal_path(parsed.path):
            continue
        return href

    return None


def _extract_resource_url(html: str, *, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")

    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, str(anchor["href"]))
        if not _is_http_url(href):
            continue
        if "/pluginfile.php/" in href or _path_looks_like_file(href):
            return href

    return None


def _extract_response_text(response: httpx.Response) -> str:
    if not _response_has_extractable_text(response):
        return ""

    body = response.text
    if _response_is_html(response):
        body = BeautifulSoup(body, "lxml").get_text("\n", strip=True)

    return _truncate_text(body)


def _extract_pdf_text(content: bytes) -> str:
    if fitz is None or not content:
        return ""

    fitz_module: Any = fitz

    try:
        document = fitz_module.open(stream=content, filetype="pdf")
    except Exception:  # noqa: BLE001
        return ""

    try:
        parts: list[str] = []
        total_length = 0
        page_count = int(document.page_count)
        for page_index in range(min(page_count, _MAX_PDF_PAGES)):
            try:
                text = str(document.load_page(page_index).get_text("text")).strip()
            except Exception:  # noqa: BLE001
                continue
            if not text:
                continue
            parts.append(text)
            total_length += len(text)
            if total_length >= _MAX_INGESTION_CHARS:
                break
    finally:
        document.close()

    return _truncate_text("\n".join(parts))


def _build_content_info(url: str, response: httpx.Response | None) -> ContentInfo:
    return ContentInfo(
        filename=_extract_filename(url, response),
        fileurl=url,
        filesize=_extract_filesize(response),
        mimetype=_response_mimetype(response),
    )


def _extract_filename(url: str, response: httpx.Response | None) -> str:
    if response is not None:
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition)
        if match:
            return match.group(1)

    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _extract_filesize(response: httpx.Response | None) -> int:
    if response is None:
        return 0

    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit():
        return int(content_length)

    return len(response.content)


def _response_mimetype(response: httpx.Response | None) -> str:
    if response is None:
        return ""
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _response_is_html(response: httpx.Response) -> bool:
    return _response_mimetype(response) == "text/html"


def _is_moodle_internal_path(path: str) -> bool:
    normalized_path = path.rstrip("/") or "/"
    return any(
        normalized_path == prefix.rstrip("/") or normalized_path.startswith(prefix)
        for prefix in _MOODLE_INTERNAL_PATH_PREFIXES
    )


def _response_has_extractable_text(response: httpx.Response) -> bool:
    mimetype = _response_mimetype(response)
    return mimetype in {"text/html", "text/plain"}


def _response_is_pdf(response: httpx.Response, url: str) -> bool:
    mimetype = _response_mimetype(response)
    return mimetype == "application/pdf" or urlparse(url).path.lower().endswith(".pdf")


def _looks_like_download(url: str, response: httpx.Response) -> bool:
    if _response_is_pdf(response, url):
        return True
    if _response_mimetype(response) and _response_mimetype(response) != "text/html":
        return True
    disposition = response.headers.get("content-disposition", "")
    return "attachment" in disposition.lower() or _path_looks_like_file(url)


def _path_looks_like_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "." in path.rsplit("/", 1)[-1]


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_login_url(url: str, host: str) -> bool:
    parsed = urlparse(url)
    host_name = urlparse(host).hostname
    return parsed.hostname == host_name and parsed.path.startswith("/login")


def _merge_description(existing: str, addition: str) -> str:
    addition = addition.strip()
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing}\n\n{addition}"


def _truncate_text(text: str) -> str:
    normalized = text.strip()
    if len(normalized) <= _MAX_INGESTION_CHARS:
        return normalized
    return normalized[:_MAX_INGESTION_CHARS].rstrip()
