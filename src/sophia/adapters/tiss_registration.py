"""TISS registration adapter — authenticated course and group registration.

Handles the JSF-based registration flow on TISS, including ViewState
management, group scraping, and preference-based registration attempts.
"""

from __future__ import annotations

import re
import warnings
from datetime import UTC, datetime
from random import randint
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunsplit

import httpx
import structlog
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from sophia.domain.errors import AuthError, RegistrationError
from sophia.domain.models import (
    FavoriteCourse,
    RegistrationGroup,
    RegistrationResult,
    RegistrationStatus,
    RegistrationTarget,
    RegistrationType,
)

if TYPE_CHECKING:
    from sophia.adapters.auth import TissSessionCredentials

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = structlog.get_logger()

_COURSE_REG_PATH = "/education/course/courseRegistration.xhtml"
_GROUP_LIST_PATH = "/education/course/groupList.xhtml"
_FAVORITES_PATH = "/education/favorites.xhtml"
_VIEWSTATE_NAMES = ("jakarta.faces.ViewState", "javax.faces.ViewState")
_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}")
_CAPACITY_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_DELTASPIKE_REDIRECT_RE = re.compile(
    r"var\s+redirectUrl\s*=\s*'([^']+)'"
)


def _extract_deltaspike_redirect(soup: BeautifulSoup) -> str | None:
    """Detect the Deltaspike window-handler loading page and return redirect URL.

    TISS wraps initial page loads in a JS-based redirect for window-ID
    negotiation.  Since we can't execute JS, we replicate what the
    ``handleWindowId`` function does: generate a window ID and request
    token, then build the redirect URL with ``dsrid`` / ``dswid`` params.
    """
    title = soup.find("title")
    if not title or "Loading" not in title.get_text():
        return None
    for script in soup.find_all("script"):
        text = script.string or ""
        m = _DELTASPIKE_REDIRECT_RE.search(text)
        if m:
            raw = (
                m.group(1)
                .replace(r"\/", "/")
                .encode("utf-8")
                .decode("unicode_escape")
            )
            return raw
    return None


def _build_deltaspike_url(
    base_url: str, redirect_path: str, http: httpx.AsyncClient
) -> str:
    """Build the Deltaspike redirect URL with proper window-ID tokens.

    Replicates the browser-side ``handleWindowId`` JS flow:
    1. Generate a random 4-digit window ID (``dswid``).
    2. Generate a random request token (``dsrid``).
    3. Set a short-lived ``dsrwid-<token>`` cookie mapping to the window ID.
    4. Append both params to the redirect URL.
    """
    window_id = str(randint(1000, 9999))
    request_token = str(randint(0, 998))
    http.cookies.set(f"dsrwid-{request_token}", window_id)

    full_url = urljoin(base_url, redirect_path)
    parsed = urlparse(full_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["dsrid"] = [request_token]
    params["dswid"] = [window_id]
    new_query = urlencode(params, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, ""))


def _clean(number: str) -> str:
    """Remove dots from course number: '186.866' → '186866'."""
    return number.replace(".", "")


def _viewstate(soup: BeautifulSoup) -> str:
    """Extract the JSF ViewState token, trying both jakarta and javax."""
    for name in _VIEWSTATE_NAMES:
        tag = soup.find("input", {"name": name})
        if tag and tag.get("value"):  # type: ignore[union-attr]
            return str(tag["value"])  # type: ignore[index]
    raise RegistrationError("ViewState token not found on page")


def _form_info(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (action, form_id) of the main POST form (skips logout forms)."""
    for form in soup.find_all("form", method=re.compile(r"post", re.IGNORECASE)):
        action, fid = str(form.get("action", "")), str(form.get("id", ""))
        if "logout" in action.lower() or "logout" in fid.lower():
            continue
        if action:
            return action, fid
    raise RegistrationError("No suitable POST form found on page")


def _button_by_text(el: BeautifulSoup | Tag, text: str) -> Tag | None:
    """Find a <button> whose visible text contains *text*."""
    for btn in el.find_all("button"):
        if hasattr(btn, "get_text") and text in btn.get_text(strip=True):
            return btn  # type: ignore[return-value]
    return None


def _detect_status(soup: BeautifulSoup) -> RegistrationStatus:
    """Determine registration status from page indicators."""
    text = soup.get_text(" ", strip=True).lower()
    if soup.find("input", {"value": "Abmelden"}) or "abmelden" in text:
        return RegistrationStatus.REGISTERED
    if soup.find("input", {"value": "Anmelden"}) or _button_by_text(soup, "Anmelden"):
        return RegistrationStatus.OPEN
    if "warteliste" in text:
        return RegistrationStatus.FULL
    if "nicht möglich" in text or "geschlossen" in text:
        return RegistrationStatus.CLOSED
    return RegistrationStatus.PENDING


def _check_result(soup: BeautifulSoup) -> tuple[bool, str]:
    """Check a response page for success/failure indicators."""
    text = soup.get_text(" ", strip=True).lower()
    if "erfolgreich" in text or "successfully" in text:
        return True, "Registration successful"
    if "bereits angemeldet" in text:
        return True, "Already registered"
    if "warteliste" in text:
        return True, "Placed on waiting list"
    if "fehler" in text or "error" in text or "nicht möglich" in text:
        return False, "Registration failed"
    return False, "Awaiting confirmation"


def _parse_group_row(row: Tag, idx: int) -> RegistrationGroup:
    """Parse a single group row/container into a RegistrationGroup.

    Index-based cell access is inherently tied to TISS's current HTML
    layout and may need adjustment when TISS changes its markup.
    """
    cells = row.find_all("td") if row.name == "tr" else row.find_all("span")
    texts: list[str] = [c.get_text(strip=True) for c in cells]

    cap, enr = 0, 0
    for t in texts:
        m = _CAPACITY_RE.search(t)
        if m:
            enr, cap = int(m.group(1)), int(m.group(2))

    time_start, time_end = "", ""
    if len(texts) >= 4:
        parts = texts[2].split("-")
        time_start = parts[0].strip()
        time_end = parts[1].strip() if len(parts) > 1 else ""

    btn: Tag | None = row.find("input", {"value": "Anmelden"})  # type: ignore[assignment]
    if not btn:
        btn = _button_by_text(row, "Anmelden")
    bid = str(btn.attrs.get("id") or btn.attrs.get("name") or "") if btn else ""

    return RegistrationGroup(
        group_id=bid or f"group-{idx}",
        name=texts[0] if texts else f"Group {idx + 1}",
        day=texts[1] if len(texts) >= 3 else "",
        time_start=time_start,
        time_end=time_end,
        location=texts[3] if len(texts) >= 5 else "",
        capacity=cap,
        enrolled=enr,
        status=RegistrationStatus.OPEN if btn else RegistrationStatus.CLOSED,
        register_button_id=bid,
    )


class TissRegistrationAdapter:
    """Authenticated TISS registration client.

    Satisfies: RegistrationProvider protocol.
    """

    def __init__(
        self, http: httpx.AsyncClient, credentials: TissSessionCredentials, host: str
    ) -> None:
        self._http = http
        self._host = host.rstrip("/")
        self._restore_cookies(http, credentials)

    @staticmethod
    def _restore_cookies(
        http: httpx.AsyncClient, credentials: TissSessionCredentials,
    ) -> None:
        """Restore all session cookies from stored credentials.

        Prefers the full cookie jar (``cookies`` field) when available.
        Falls back to the legacy ``jsessionid`` / ``tiss_session`` fields
        for backward compatibility with session files created before the
        full-jar support was added.
        """
        import json

        jar: dict[str, str] = {}
        if credentials.cookies and credentials.cookies != "{}":
            try:
                jar = json.loads(credentials.cookies)
            except (json.JSONDecodeError, TypeError):
                jar = {}

        if jar:
            for name, value in jar.items():
                http.cookies.set(name, value)
        else:
            # Legacy fallback: only admin-context cookies were stored
            http.cookies.set("JSESSIONID", credentials.jsessionid)
            http.cookies.set("_tiss_session", credentials.tiss_session)
            http.cookies.set("dsrwid-1", "1")

    # --- HTTP helpers with auth-redirect detection ---

    async def _get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> tuple[BeautifulSoup, httpx.Response]:
        """GET a TISS page; follows Deltaspike window-handler redirects.

        TISS uses DeltaSpike's client-side window-ID negotiation for JSF
        pages.  The first request returns a "Loading..." page with JS that
        assigns a window ID and redirects.  We replicate that JS flow:
        generate ``dsrid``/``dswid`` tokens, set the ``dsrwid-*`` cookie,
        and follow the redirect ourselves.
        """
        log.debug("tiss_reg.fetch", url=url)
        try:
            resp = await self._http.get(url, params=params or {})
        except httpx.HTTPError as exc:
            raise RegistrationError(f"HTTP request failed: {url}") from exc

        soup, resp = self._parse(resp)
        redirect_path = _extract_deltaspike_redirect(soup)
        if redirect_path:
            redirect_url = _build_deltaspike_url(
                str(resp.url), redirect_path, self._http
            )
            log.debug("tiss_reg.deltaspike_redirect", url=redirect_url)
            try:
                resp = await self._http.get(redirect_url)
            except httpx.HTTPError as exc:
                raise RegistrationError(f"HTTP request failed: {redirect_url}") from exc
            soup, resp = self._parse(resp)

        return soup, resp

    async def _post(
        self, url: str, data: dict[str, str]
    ) -> tuple[BeautifulSoup, httpx.Response]:
        """POST a JSF form; raises AuthError on login redirect."""
        log.debug("tiss_reg.submit", url=url)
        try:
            resp = await self._http.post(url, data=data)
        except httpx.HTTPError as exc:
            raise RegistrationError(f"POST failed: {url}") from exc
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> tuple[BeautifulSoup, httpx.Response]:
        if "authentifizierung" in str(resp.url).lower():
            raise AuthError("TISS session expired — log in again")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RegistrationError(f"HTTP {exc.response.status_code}") from exc
        return BeautifulSoup(resp.text, "lxml"), resp

    # --- RegistrationProvider protocol ---

    async def get_registration_status(
        self, course_number: str, semester: str
    ) -> RegistrationTarget:
        """Fetch the LVA registration page and parse registration status."""
        url = f"{self._host}{_COURSE_REG_PATH}"
        params = {"courseNr": _clean(course_number), "semester": semester, "windowId": "1"}
        soup, _ = await self._get(url, params)

        dates = _DATE_RE.findall(soup.get_text(" ", strip=True))
        h1 = soup.find("h1")
        detected_status = _detect_status(soup)
        log.info("tiss_reg.status", course=course_number, status=detected_status.value)

        return RegistrationTarget(
            course_number=course_number,
            semester=semester,
            registration_type=RegistrationType.LVA,
            title=h1.get_text(strip=True) if h1 else "",
            registration_start=dates[0] if dates else None,
            registration_end=dates[1] if len(dates) >= 2 else None,
            status=detected_status,
        )

    async def get_groups(
        self, course_number: str, semester: str
    ) -> list[RegistrationGroup]:
        """Fetch available groups for a course from the group list page."""
        url = f"{self._host}{_GROUP_LIST_PATH}"
        params = {"courseNr": _clean(course_number), "semester": semester, "windowId": "1"}
        soup, _ = await self._get(url, params)

        rows: list[Tag] = soup.find_all(class_="groupWrapper")  # type: ignore[assignment]
        if not rows:
            table = soup.find("table", class_="group")
            if table:
                rows = [tr for tr in table.find_all("tr") if tr.find("td")]  # type: ignore[union-attr]

        groups = [_parse_group_row(c, i) for i, c in enumerate(rows)]
        log.info("tiss_reg.groups", course=course_number, count=len(groups))
        return groups

    async def get_favorites(self, semester: str) -> list[FavoriteCourse]:
        """Fetch the user's favorited courses from TISS."""
        url = f"{self._host}{_FAVORITES_PATH}"
        params = {"semester": semester, "windowId": "1"}
        soup, _ = await self._get(url, params)
        favorites = _parse_favorites(soup, semester)
        log.info("tiss_reg.favorites", semester=semester, count=len(favorites))
        return favorites

    async def register(
        self, course_number: str, semester: str, group_id: str | None = None
    ) -> RegistrationResult:
        """Submit a registration using the 2-step JSF flow."""
        rtype = RegistrationType.GROUP if group_id else RegistrationType.LVA
        path = _GROUP_LIST_PATH if group_id else _COURSE_REG_PATH
        params = {"courseNr": _clean(course_number), "semester": semester, "windowId": "1"}

        soup, resp = await self._get(f"{self._host}{path}", params)
        vs = _viewstate(soup)
        action, fid = _form_info(soup)

        btn = self._find_btn(soup, group_id)
        if not btn:
            return _result(course_number, rtype, group_id, ok=False,
                           msg="No register button found on page")

        # Step 1: POST the register form
        post_data = _build_post(fid, vs, soup, btn)
        csoup, cresp = await self._post(urljoin(str(resp.url), action), post_data)

        ok, msg = _check_result(csoup)
        if ok:
            return _result(course_number, rtype, group_id, ok=True, msg=msg)

        # Step 2: Confirmation page
        cbtn = _find_confirm_btn(csoup)
        if not cbtn:
            return _result(course_number, rtype, group_id, ok=True, msg=msg)

        try:
            cvs = _viewstate(csoup)
        except RegistrationError:
            return _result(course_number, rtype, group_id, ok=False,
                           msg="Confirmation page missing ViewState")

        cact, cfid = _form_info(csoup)
        fsoup, _ = await self._post(urljoin(str(cresp.url), cact),
                                    _build_post(cfid, cvs, csoup, cbtn))
        fok, fmsg = _check_result(fsoup)
        log.info("tiss_reg.register", course=course_number, group=group_id, success=fok)
        return _result(course_number, rtype, group_id, ok=fok, msg=fmsg)

    @staticmethod
    def _find_btn(soup: BeautifulSoup, group_id: str | None) -> Tag | None:
        """Locate register button, optionally scoped to a group."""
        result: Tag | None
        if group_id:
            result = soup.find("input", {"name": group_id, "value": "Anmelden"})  # type: ignore[assignment]
            if result:
                return result
            result = soup.find("input", {"id": group_id})  # type: ignore[assignment]
            if result:
                return result
            result = soup.find("button", {"id": group_id})  # type: ignore[assignment]
            return result
        result = soup.find("input", {"value": "Anmelden"})  # type: ignore[assignment]
        return result or _button_by_text(soup, "Anmelden")


# --- Module-level helpers ---


_COURSE_NR_RE = re.compile(r"(\d{3}\.[A-Z0-9]{3})")
_COURSE_TYPE_RE = re.compile(r"\b(VU|VO|UE|SE|PR|EX|LU|KO)\b")


def _has_checkmark(cell: Tag) -> bool:
    """Detect a registration checkmark (tick-circle icon) in a table cell."""
    img = cell.find("img")
    return bool(img and "tick" in str(img.get("src", "")).lower())


def _parse_favorites(soup: BeautifulSoup, semester: str) -> list[FavoriteCourse]:
    """Parse the TISS favorites page into FavoriteCourse objects.

    The page uses a PrimeFaces DataTable with CSS-classed cells:
    favoritesTitleCol, favoritesH, favoritesECTS, favoritesReg,
    favoritesGrp, favoritesExam. The title cell contains the course name
    and a <span class="gray"> subtitle with course number, type, semester.
    """
    results: list[FavoriteCourse] = []

    for row in soup.find_all("tr", attrs={"data-ri": True}):
        title_td: Tag | None = row.find("td", class_="favoritesTitleCol")  # type: ignore[assignment]
        if not title_td:
            continue

        # Title: first <a> text
        link = title_td.find("a")
        title = link.get_text(strip=True) if link else ""

        # Subtitle: <span class="gray"> contains LVA Nr, Typ, Semester
        gray = title_td.find("span", class_="gray")
        course_number, course_type, sem = "", "", semester
        if gray:
            nr_span = gray.find("span", title="LVA Nr.")
            if nr_span:
                course_number = nr_span.get_text(strip=True)
            type_span = gray.find("span", title="Typ")
            if type_span:
                raw = type_span.get_text(strip=True).strip(", ")
                type_match = _COURSE_TYPE_RE.search(raw)
                course_type = type_match.group(1) if type_match else raw
            sem_span = gray.find("span", title="Semester")
            if sem_span:
                sem = sem_span.get_text(strip=True)

        if not course_number:
            continue

        # Numeric columns
        h_td = row.find("td", class_="favoritesH")
        e_td = row.find("td", class_="favoritesECTS")
        hours = _safe_float(h_td.get_text(strip=True)) if h_td else 0.0
        ects = _safe_float(e_td.get_text(strip=True)) if e_td else 0.0

        # Registration checkmarks
        reg_td: Tag | None = row.find("td", class_="favoritesReg")  # type: ignore[assignment]
        grp_td: Tag | None = row.find("td", class_="favoritesGrp")  # type: ignore[assignment]
        exam_td: Tag | None = row.find("td", class_="favoritesExam")  # type: ignore[assignment]

        results.append(FavoriteCourse(
            course_number=course_number,
            title=title,
            course_type=course_type,
            semester=sem,
            hours=hours,
            ects=ects,
            lva_registered=_has_checkmark(reg_td) if reg_td else False,
            group_registered=_has_checkmark(grp_td) if grp_td else False,
            exam_registered=_has_checkmark(exam_td) if exam_td else False,
        ))

    return results


def _safe_float(text: str) -> float:
    """Parse a float from text, returning 0.0 on failure."""
    try:
        return float(text.replace(",", "."))
    except (ValueError, AttributeError):
        return 0.0


def _find_confirm_btn(soup: BeautifulSoup) -> Tag | None:
    for label in ("Bestätigen", "OK", "Ja"):
        tag: Tag | None = soup.find("input", {"value": label})  # type: ignore[assignment]
        if tag:
            return tag
    return None


def _build_post(fid: str, vs: str, soup: BeautifulSoup, btn: Tag) -> dict[str, str]:
    data: dict[str, str] = {
        fid: fid,
        str(btn.get("name") or btn.get("id") or ""): str(btn.get("value") or "Anmelden"),
    }
    for name in _VIEWSTATE_NAMES:
        if soup.find("input", {"name": name}):
            data[name] = vs
            break
    return data


def _result(
    course_number: str, rtype: RegistrationType, group_id: str | None,
    *, ok: bool, msg: str,
) -> RegistrationResult:
    return RegistrationResult(
        course_number=course_number, registration_type=rtype,
        success=ok, group_name=group_id or "", message=msg,
        attempted_at=datetime.now(UTC).isoformat(),
    )
