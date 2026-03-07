"""Tests for TISS registration adapter."""

from __future__ import annotations

import httpx
import pytest
import respx

from sophia.adapters.auth import TissSessionCredentials
from sophia.adapters.tiss_registration import (
    TissRegistrationAdapter,
    _clean,  # pyright: ignore[reportPrivateUsage]
    _detect_status,  # pyright: ignore[reportPrivateUsage]
    _viewstate,  # pyright: ignore[reportPrivateUsage]
)
from sophia.domain.errors import AuthError, RegistrationError
from sophia.domain.models import RegistrationStatus

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


class TestViewstate:
    def test_extracts_jakarta(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(TISS_REG_PAGE_OPEN, "lxml")
        assert _viewstate(soup) == "VIEWSTATE_ABC123"

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
        ).mock(return_value=httpx.Response(
            302,
            headers={"Location": "https://tiss.tuwien.ac.at/admin/authentifizierung"},
        ))
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
        assert "button" in result.message.lower()


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
        ).mock(return_value=httpx.Response(
            302,
            headers={"Location": "https://tiss.tuwien.ac.at/admin/authentifizierung"},
        ))
        respx.get(
            "https://tiss.tuwien.ac.at/admin/authentifizierung",
        ).mock(return_value=httpx.Response(200, html="<html>Login</html>"))

        async with httpx.AsyncClient(follow_redirects=True) as http:
            adapter = TissRegistrationAdapter(
                http=http, credentials=_make_creds(), host="https://tiss.tuwien.ac.at"
            )
            with pytest.raises(AuthError, match="session expired"):
                await adapter.get_favorites("2026S")
