"""Tests for TISS registration adapter."""

from __future__ import annotations

import httpx
import pytest
import respx

from sophia.adapters.auth import TissSessionCredentials
from sophia.adapters.tiss_registration import (
    TissRegistrationAdapter,
    _build_deltaspike_url,  # pyright: ignore[reportPrivateUsage]
    _button_by_text,  # pyright: ignore[reportPrivateUsage]
    _clean,  # pyright: ignore[reportPrivateUsage]
    _detect_status,  # pyright: ignore[reportPrivateUsage]
    _extract_deltaspike_redirect,  # pyright: ignore[reportPrivateUsage]
    _find_confirm_btn,  # pyright: ignore[reportPrivateUsage]
    _form_info,  # pyright: ignore[reportPrivateUsage]
    _safe_float,  # pyright: ignore[reportPrivateUsage]
    _viewstate,  # pyright: ignore[reportPrivateUsage]
)
from sophia.domain.errors import AuthError, RegistrationError
from sophia.domain.models import RegistrationStatus

HOST = "https://tiss.tuwien.ac.at"

# --- HTML Fixtures ---

TISS_FAVORITES_PAGE = (
    "<html><body><h1>Favoriten</h1>"
    '<form id="contentForm" method="post"'
    ' action="/education/favorites.xhtml">'
    '<input type="hidden"'
    ' name="jakarta.faces.ViewState" value="VS_FAV" />'
    '<table role="grid"><tbody class="ui-datatable-data">'
    # --- row 0 ---
    '<tr data-ri="0" class="ui-widget-content">'
    '<td class="favoritesActionCol"></td>'
    '<td class="favoritesTitleCol">'
    '<a href="/course/educationDetails.xhtml?courseNr=185A91">'
    "Einführung in die Programmierung 1</a>"
    '<br/><span class="gray">'
    '<span title="LVA Nr.">185.A91</span>'
    '<span title="Typ">, VU, </span>'
    '<span title="Semester">2026S</span>'
    "</span></td>"
    '<td class="favoritesH">4.0</td>'
    '<td class="favoritesECTS">5.5</td>'
    '<td class="favoritesReg">'
    '<a href="#"><img src="/icons/tick-circle.png"'
    ' alt="Angemeldet"/></a></td>'
    '<td class="favoritesGrp"></td>'
    '<td class="favoritesExam">'
    '<a href="#"><span>9</span></a></td></tr>'
    # --- row 1 ---
    '<tr data-ri="1" class="ui-widget-content">'
    '<td class="favoritesActionCol"></td>'
    '<td class="favoritesTitleCol">'
    '<a href="/course/educationDetails.xhtml?courseNr=104634">'
    "Analysis für Informatik</a>"
    '<br/><span class="gray">'
    '<span title="LVA Nr.">104.634</span>'
    '<span title="Typ">, VU, </span>'
    '<span title="Semester">2026S</span>'
    "</span></td>"
    '<td class="favoritesH">4.0</td>'
    '<td class="favoritesECTS">6.0</td>'
    '<td class="favoritesReg"></td>'
    '<td class="favoritesGrp">'
    '<a href="#"><img src="/icons/tick-circle.png"'
    ' alt="Angemeldet"/></a></td>'
    '<td class="favoritesExam"></td></tr>'
    # --- row 2 ---
    '<tr data-ri="2" class="ui-widget-content">'
    '<td class="favoritesActionCol"></td>'
    '<td class="favoritesTitleCol">'
    '<a href="/course/educationDetails.xhtml?courseNr=104260">'
    "Algebra und Diskrete Mathematik</a>"
    '<br/><span class="gray">'
    '<span title="LVA Nr.">104.260</span>'
    '<span title="Typ">, VO, </span>'
    '<span title="Semester">2025W</span>'
    "</span></td>"
    '<td class="favoritesH">3.0</td>'
    '<td class="favoritesECTS">4.0</td>'
    '<td class="favoritesReg"></td>'
    '<td class="favoritesGrp"></td>'
    '<td class="favoritesExam"></td></tr>'
    "</tbody></table></form></body></html>"
)

TISS_FAVORITES_EMPTY = """
<html><body>
<h1>Favoriten</h1>
<form id="contentForm" method="post" action="/education/favorites.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_FAV_EMPTY" />
    <table role="grid"><tbody class="ui-datatable-data"></tbody></table>
</form>
</body></html>
"""

TISS_INVALID_COURSE_PAGE = """
<html><body>
<h1>Error</h1>
<p>Die angegebene Lehrveranstaltung wurde nicht gefunden.</p>
</body></html>
"""

TISS_REG_PAGE_OPEN = """
<html><body>
<h1>Algorithmen und Datenstrukturen 1 VU</h1>
<form id="registrationForm" method="post" action="/education/course/courseRegistration.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VIEWSTATE_ABC123" />
    <span>Anmeldefrist: 01.03.2026 08:00 bis 15.03.2026 23:59</span>
    <input type="submit" name="registrationForm:registerBtn" value="Anmelden"
           id="registrationForm:registerBtn" />
    <input type="hidden" name="registrationForm" value="registrationForm" />
</form>
</body></html>
"""

TISS_REG_PAGE_REGISTERED = """
<html><body>
<h1>Algorithmen und Datenstrukturen 1 VU</h1>
<form id="registrationForm" method="post" action="/education/course/courseRegistration.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_REG" />
    <span>Sie sind bereits angemeldet.</span>
    <input type="submit" name="registrationForm:deregisterBtn" value="Abmelden" />
    <input type="hidden" name="registrationForm" value="registrationForm" />
</form>
</body></html>
"""

TISS_REG_PAGE_CLOSED = """
<html><body>
<h1>Algorithmen und Datenstrukturen 1 VU</h1>
<form id="registrationForm" method="post" action="/education/course/courseRegistration.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_CLOSED" />
    <p>Anmeldung derzeit nicht möglich.</p>
    <input type="hidden" name="registrationForm" value="registrationForm" />
</form>
</body></html>
"""

TISS_GROUP_PAGE = """
<html><body>
<h1>Groups for 186.813</h1>
<form id="groupForm" method="post" action="/education/course/groupList.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_GROUPS" />
    <input type="hidden" name="groupForm" value="groupForm" />
    <table class="group">
        <tr class="groupWrapper">
            <td>Group 1 - Mo</td><td>Monday</td><td>09:00-11:00</td>
            <td>Seminarraum</td><td>15 / 30</td>
            <td><input type="submit" name="groupForm:reg0" value="Anmelden"
                       id="groupForm:reg0" /></td>
        </tr>
        <tr class="groupWrapper">
            <td>Group 2 - Di</td><td>Tuesday</td><td>14:00-16:00</td>
            <td>HS1</td><td>30 / 30</td>
        </tr>
        <tr class="groupWrapper">
            <td>Group 3 - Mi</td><td>Wednesday</td><td>10:00-12:00</td>
            <td>Lab</td><td>20 / 25</td>
            <td><input type="submit" name="groupForm:reg2" value="Anmelden"
                       id="groupForm:reg2" /></td>
        </tr>
    </table>
</form>
</body></html>
"""

TISS_REG_SUCCESS = """
<html><body>
<form id="confirmForm" method="post" action="/education/course/register.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_CONFIRM" />
    <p>Anmeldung erfolgreich durchgeführt.</p>
    <input type="hidden" name="confirmForm" value="confirmForm" />
</form>
</body></html>
"""

TISS_REG_CONFIRM = """
<html><body>
<form id="confirmForm" method="post" action="/education/course/register.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_CONFIRM2" />
    <p>Bitte bestätigen Sie die Anmeldung.</p>
    <input type="submit" name="confirmForm:ok" value="Bestätigen" id="confirmForm:ok" />
    <input type="hidden" name="confirmForm" value="confirmForm" />
</form>
</body></html>
"""

TISS_REG_AFTER_CONFIRM = """
<html><body>
<form id="resultForm" method="post" action="/education/course/result.xhtml">
    <input type="hidden" name="jakarta.faces.ViewState" value="VS_FINAL" />
    <p>Anmeldung erfolgreich durchgeführt.</p>
    <input type="hidden" name="resultForm" value="resultForm" />
</form>
</body></html>
"""


def _make_creds() -> TissSessionCredentials:
    return TissSessionCredentials(
        jsessionid="JSID_TEST",
        tiss_session="TISS_TEST",
        host="https://tiss.tuwien.ac.at",
        created_at="2026-03-06T00:00:00+00:00",
    )


# --- Unit tests for helpers ---


class TestClean:
    def test_removes_dot(self):
        assert _clean("186.813") == "186813"

    def test_no_dot(self):
        assert _clean("186813") == "186813"


class TestDetectStatus:
    def test_open(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(TISS_REG_PAGE_OPEN, "lxml")
        assert _detect_status(soup) == RegistrationStatus.OPEN

    def test_registered(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(TISS_REG_PAGE_REGISTERED, "lxml")
        assert _detect_status(soup) == RegistrationStatus.REGISTERED

    def test_closed(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(TISS_REG_PAGE_CLOSED, "lxml")
        assert _detect_status(soup) == RegistrationStatus.CLOSED

    def test_full_warteliste(self):
        from bs4 import BeautifulSoup

        html = "<html><body><p>Sie stehen auf der Warteliste.</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _detect_status(soup) == RegistrationStatus.FULL

    def test_pending_minimal(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<html><body><p>Kursinfos</p></body></html>", "lxml")
        assert _detect_status(soup) == RegistrationStatus.PENDING


class TestViewstate:
    def test_extracts_jakarta(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(TISS_REG_PAGE_OPEN, "lxml")
        assert _viewstate(soup) == "VIEWSTATE_ABC123"

    def test_extracts_javax(self):
        from bs4 import BeautifulSoup

        html = (
            "<html><body><form>"
            '<input type="hidden" name="javax.faces.ViewState" value="VS_JAVAX"/>'
            "</form></body></html>"
        )
        soup = BeautifulSoup(html, "lxml")
        assert _viewstate(soup) == "VS_JAVAX"

    def test_raises_when_missing(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        with pytest.raises(RegistrationError, match="ViewState"):
            _viewstate(soup)


# --- Integration tests for adapter ---


class TestGetRegistrationStatus:
    @respx.mock
    async def test_open_status(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_PAGE_OPEN))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            target = await adapter.get_registration_status("186.813", "2026S")

        assert target.status == RegistrationStatus.OPEN
        assert target.course_number == "186.813"
        assert "Algorithmen" in target.title

    @respx.mock
    async def test_registered_status(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_PAGE_REGISTERED))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            target = await adapter.get_registration_status("186.813", "2026S")

        assert target.status == RegistrationStatus.REGISTERED

    @respx.mock
    async def test_auth_redirect_raises(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(
            return_value=httpx.Response(
                302,
                headers={"Location": "https://tiss.tuwien.ac.at/admin/authentifizierung"},
            )
        )
        respx.get(
            "https://tiss.tuwien.ac.at/admin/authentifizierung",
        ).mock(return_value=httpx.Response(200, html="<html>Login</html>"))

        async with httpx.AsyncClient(follow_redirects=True) as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            with pytest.raises(AuthError, match="session expired"):
                await adapter.get_registration_status("186.813", "2026S")


class TestGetGroups:
    @respx.mock
    async def test_parses_groups(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/groupList.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_GROUP_PAGE))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            grps = await adapter.get_groups("186.813", "2026S")

        assert len(grps) == 3
        assert grps[0].name == "Group 1 - Mo"
        assert grps[0].status == RegistrationStatus.OPEN
        assert grps[0].register_button_id == "groupForm:reg0"
        assert grps[1].status == RegistrationStatus.CLOSED
        assert grps[2].register_button_id == "groupForm:reg2"

    @respx.mock
    async def test_empty_groups(self):
        empty_html = "<html><body><form id='f' method='post' action='/'></form></body></html>"
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/groupList.xhtml",
        ).mock(return_value=httpx.Response(200, html=empty_html))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            grps = await adapter.get_groups("186.813", "2026S")
        assert grps == []


class TestRegister:
    @respx.mock
    async def test_lva_registration_success(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_PAGE_OPEN))
        respx.post(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_SUCCESS))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            result = await adapter.register("186.813", "2026S")

        assert result.success
        assert "successful" in result.message.lower() or "erfolgreich" in result.message.lower()

    @respx.mock
    async def test_registration_with_confirmation(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_PAGE_OPEN))
        respx.post(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_CONFIRM))
        respx.post(
            "https://tiss.tuwien.ac.at/education/course/register.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_AFTER_CONFIRM))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            result = await adapter.register("186.813", "2026S")

        assert result.success

    @respx.mock
    async def test_group_registration(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/groupList.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_GROUP_PAGE))
        respx.post(
            "https://tiss.tuwien.ac.at/education/course/groupList.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_SUCCESS))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            result = await adapter.register("186.813", "2026S", group_id="groupForm:reg0")

        assert result.success

    @respx.mock
    async def test_no_register_button(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_REG_PAGE_CLOSED))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            result = await adapter.register("186.813", "2026S")

        assert not result.success
        assert "registration may be closed" in result.message.lower()

    @respx.mock
    async def test_invalid_course_returns_failure(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/course/courseRegistration.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_INVALID_COURSE_PAGE))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            result = await adapter.register("5", "2026S")

        assert not result.success
        assert "registration form" in result.message.lower()


class TestExtractDeltaspikeRedirect:
    def test_returns_redirect_url(self):
        from bs4 import BeautifulSoup

        html = (
            "<html><head><title>Loading</title></head><body>"
            "<script>var redirectUrl = '/education/favorites.xhtml?q=1';</script>"
            "</body></html>"
        )
        soup = BeautifulSoup(html, "lxml")
        url = _extract_deltaspike_redirect(soup)  # pyright: ignore[reportPrivateUsage]
        assert url == "/education/favorites.xhtml?q=1"

    def test_returns_none_no_loading_title(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<html><head><title>Home</title></head></html>", "lxml")
        assert _extract_deltaspike_redirect(soup) is None  # pyright: ignore[reportPrivateUsage]


class TestBuildDeltaspikeUrl:
    def test_adds_dsrid_dswid(self):
        import asyncio

        async def _run():
            async with httpx.AsyncClient() as client:
                url = _build_deltaspike_url(  # pyright: ignore[reportPrivateUsage]
                    "https://tiss.tuwien.ac.at/education/favorites.xhtml",
                    "/education/favorites.xhtml?dswid=123",
                    client,
                )
                assert "dsrid=" in url
                assert "dswid=" in url

        asyncio.run(_run())


class TestSafeFloat:
    def test_parses_int(self):
        assert _safe_float("4") == 4.0  # pyright: ignore[reportPrivateUsage]

    def test_parses_decimal(self):
        assert _safe_float("5.5") == 5.5  # pyright: ignore[reportPrivateUsage]

    def test_parses_comma_decimal(self):
        assert _safe_float("6,5") == 6.5  # pyright: ignore[reportPrivateUsage]

    def test_returns_zero_on_failure(self):
        assert _safe_float("abc") == 0.0  # pyright: ignore[reportPrivateUsage]

    def test_returns_zero_on_empty(self):
        assert _safe_float("") == 0.0  # pyright: ignore[reportPrivateUsage]


class TestButtonByText:
    def test_finds_button(self):
        from bs4 import BeautifulSoup

        html = '<div><button type="submit">Anmelden</button></div>'
        soup = BeautifulSoup(html, "lxml")
        btn = _button_by_text(soup, "Anmelden")  # pyright: ignore[reportPrivateUsage]
        assert btn is not None
        assert btn.get_text(strip=True) == "Anmelden"

    def test_returns_none_when_missing(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<div></div>", "lxml")
        assert _button_by_text(soup, "Anmelden") is None  # pyright: ignore[reportPrivateUsage]


class TestFindConfirmBtn:
    def test_finds_ok(self):
        from bs4 import BeautifulSoup

        html = '<form><input type="submit" value="OK" name="f:ok"/></form>'
        soup = BeautifulSoup(html, "lxml")
        btn = _find_confirm_btn(soup)  # pyright: ignore[reportPrivateUsage]
        assert btn is not None
        assert btn["value"] == "OK"

    def test_finds_ja(self):
        from bs4 import BeautifulSoup

        html = '<form><input type="submit" value="Ja" name="f:ja"/></form>'
        soup = BeautifulSoup(html, "lxml")
        btn = _find_confirm_btn(soup)  # pyright: ignore[reportPrivateUsage]
        assert btn is not None
        assert btn["value"] == "Ja"

    def test_returns_none_when_no_match(self):
        from bs4 import BeautifulSoup

        html = '<form><input type="submit" value="Cancel" name="f:c"/></form>'
        soup = BeautifulSoup(html, "lxml")
        assert _find_confirm_btn(soup) is None  # pyright: ignore[reportPrivateUsage]


class TestFormInfo:
    def test_skips_logout_form(self):
        from bs4 import BeautifulSoup

        html = (
            "<html><body>"
            '<form method="post" action="/logout" id="logoutForm">'
            '<input type="hidden" name="x" value="1"/></form>'
            '<form method="post" action="/education/reg.xhtml" id="regForm">'
            '<input type="hidden" name="y" value="2"/></form>'
            "</body></html>"
        )
        soup = BeautifulSoup(html, "lxml")
        action, fid = _form_info(soup)  # pyright: ignore[reportPrivateUsage]
        assert action == "/education/reg.xhtml"
        assert fid == "regForm"

    def test_raises_when_no_post_form(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        with pytest.raises(RegistrationError, match="No suitable POST form"):
            _form_info(soup)  # pyright: ignore[reportPrivateUsage]


class TestProtocolConformance:
    """Verify TissRegistrationAdapter structurally satisfies RegistrationProvider."""

    def test_has_get_registration_status(self):
        assert hasattr(TissRegistrationAdapter, "get_registration_status")

    def test_has_get_groups(self):
        assert hasattr(TissRegistrationAdapter, "get_groups")

    def test_has_register(self):
        assert hasattr(TissRegistrationAdapter, "register")

    def test_has_get_favorites(self):
        assert hasattr(TissRegistrationAdapter, "get_favorites")


class TestGetFavorites:
    @respx.mock
    async def test_parses_favorites(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/favorites.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_FAVORITES_PAGE))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            favs = await adapter.get_favorites("2026S")

        assert len(favs) == 3

        assert favs[0].course_number == "185.A91"
        assert favs[0].title == "Einführung in die Programmierung 1"
        assert favs[0].course_type == "VU"
        assert favs[0].semester == "2026S"
        assert favs[0].hours == 4.0
        assert favs[0].ects == 5.5
        assert favs[0].lva_registered is True
        assert favs[0].group_registered is False
        assert favs[0].exam_registered is False

        assert favs[1].course_number == "104.634"
        assert favs[1].course_type == "VU"
        assert favs[1].lva_registered is False
        assert favs[1].group_registered is True
        assert favs[1].exam_registered is False
        assert favs[1].ects == 6.0

        assert favs[2].course_number == "104.260"
        assert favs[2].course_type == "VO"
        assert favs[2].semester == "2025W"
        assert favs[2].lva_registered is False

    @respx.mock
    async def test_empty_favorites(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/favorites.xhtml",
        ).mock(return_value=httpx.Response(200, html=TISS_FAVORITES_EMPTY))

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            favs = await adapter.get_favorites("2026S")

        assert favs == []

    @respx.mock
    async def test_auth_redirect_raises(self):
        respx.get(
            "https://tiss.tuwien.ac.at/education/favorites.xhtml",
        ).mock(
            return_value=httpx.Response(
                302,
                headers={"Location": "https://tiss.tuwien.ac.at/admin/authentifizierung"},
            )
        )
        respx.get(
            "https://tiss.tuwien.ac.at/admin/authentifizierung",
        ).mock(return_value=httpx.Response(200, html="<html>Login</html>"))

        async with httpx.AsyncClient(follow_redirects=True) as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            with pytest.raises(AuthError, match="session expired"):
                await adapter.get_favorites("2026S")


class TestTooManyRedirectsHandling:
    """TooManyRedirects (SSO redirect loops) should raise AuthError, not RegistrationError."""

    @respx.mock
    async def test_get_too_many_redirects_raises_auth_error(self) -> None:
        respx.get(f"{HOST}/education/course/courseRegistration.xhtml").mock(
            side_effect=httpx.TooManyRedirects("redirect loop", request=httpx.Request("GET", HOST)),
        )

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(http=http, credentials=_make_creds(), host=HOST)
            with pytest.raises(AuthError, match="session expired"):
                await adapter.get_registration_status("186.813", "2026S")

    @respx.mock
    async def test_post_too_many_redirects_raises_auth_error(self) -> None:
        # First GET succeeds (returns an open registration page)
        respx.get(f"{HOST}/education/course/courseRegistration.xhtml").mock(
            return_value=httpx.Response(200, html=TISS_REG_PAGE_OPEN),
        )
        # POST triggers TooManyRedirects (SSO loop)
        respx.post(f"{HOST}/education/course/courseRegistration.xhtml").mock(
            side_effect=httpx.TooManyRedirects(
                "redirect loop",
                request=httpx.Request("POST", HOST),
            ),
        )

        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(http=http, credentials=_make_creds(), host=HOST)
            with pytest.raises(AuthError, match="session expired"):
                await adapter.register("186.813", "2026S")

    def test_parse_detects_idp_redirect(self) -> None:
        resp = httpx.Response(
            200,
            html="<html>IdP login</html>",
            request=httpx.Request("GET", "https://idp.zid.tuwien.ac.at/simplesaml/login"),
        )
        with pytest.raises(AuthError, match="session expired"):
            TissRegistrationAdapter._parse(resp)  # pyright: ignore[reportPrivateUsage]

    def test_parse_detects_login_redirect(self) -> None:
        resp = httpx.Response(
            200,
            html="<html>Login page</html>",
            request=httpx.Request("GET", "https://tiss.tuwien.ac.at/admin/login"),
        )
        with pytest.raises(AuthError, match="session expired"):
            TissRegistrationAdapter._parse(resp)  # pyright: ignore[reportPrivateUsage]


class TestErrorMessageSanitization:
    """RegistrationError messages must never contain URLs or session tokens."""

    @respx.mock
    async def test_fetch_connect_error_does_not_leak_url(self) -> None:
        url = f"{HOST}/education/favorites.xhtml"
        respx.get(url).mock(
            side_effect=httpx.ConnectError("connection refused", request=httpx.Request("GET", url)),
        )
        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(http=http, credentials=_make_creds(), host=HOST)
            with pytest.raises(RegistrationError, match="connection") as exc_info:
                await adapter._get(url)  # pyright: ignore[reportPrivateUsage]
            assert HOST not in str(exc_info.value)

    @respx.mock
    async def test_fetch_deltaspike_redirect_error_does_not_leak_url(self) -> None:
        deltaspike_html = (
            "<html><head><title>Loading...</title></head><body>"
            "<script>var redirectUrl = '/education/favorites.xhtml';</script>"
            "</body></html>"
        )
        call_count = 0

        def _side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, html=deltaspike_html, request=request)
            raise httpx.ConnectError("connection refused", request=request)

        respx.get(url__startswith=f"{HOST}/education/favorites.xhtml").mock(
            side_effect=_side_effect,
        )
        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(http=http, credentials=_make_creds(), host=HOST)
            with pytest.raises(RegistrationError, match="connection") as exc_info:
                await adapter._get(f"{HOST}/education/favorites.xhtml")  # pyright: ignore[reportPrivateUsage]
            assert "dswid" not in str(exc_info.value)
            assert HOST not in str(exc_info.value)

    @respx.mock
    async def test_post_error_does_not_leak_url(self) -> None:
        url = f"{HOST}/education/course/courseRegistration.xhtml"
        respx.post(url).mock(
            side_effect=httpx.ConnectError(
                "connection refused", request=httpx.Request("POST", url)
            ),
        )
        async with httpx.AsyncClient() as http:
            adapter = TissRegistrationAdapter(http=http, credentials=_make_creds(), host=HOST)
            with pytest.raises(RegistrationError, match="request failed") as exc_info:
                await adapter._post(url, data={"key": "val"})  # pyright: ignore[reportPrivateUsage]
            assert HOST not in str(exc_info.value)
