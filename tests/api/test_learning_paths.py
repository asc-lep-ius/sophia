"""Learning path listing, selection, and the selection a login makes (#106)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from sophia.adapters.auth import SessionCredentials
from sophia.api.routers import auth as auth_router
from sophia.api.sessions import SessionTenant
from sophia.domain.errors import MoodleError
from sophia.domain.models import Course

from ._db_harness import db_harness
from ._session_helpers import (
    FakeAppContainer,
    FakeMoodle,
    build_harness,
    csrf_headers,
    login,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from sophia.infra.di import AppContainer

    from ._db_harness import DbHarness
    from ._session_helpers import ApiHarness

ALGORITHMS = Course(id=12, fullname="Algorithms", shortname="186.813", url="https://tu.test/12")
DATABASES = Course(id=34, fullname="Databases", shortname="184.686", url=None)


def unselected_tenant() -> SessionTenant:
    return SessionTenant(org_id="tu-wien", learning_path_id=None)


def harness_with(
    *courses: Course,
    tenant: SessionTenant | None = None,
    error: Exception | None = None,
) -> ApiHarness:
    moodle = FakeMoodle(courses=list(courses), error=error)
    return build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object(), moodle=moodle)),
        tenant=tenant or unselected_tenant(),
    )


def session_learning_path(harness: ApiHarness) -> str | None:
    return harness.client.get("/api/auth/session").json()["tenant"]["learning_path_id"]


def test_learning_path_routes_require_authentication() -> None:
    harness = harness_with(ALGORITHMS)

    list_response = harness.client.get("/api/learning-paths")
    select_response = harness.client.put(
        "/api/learning-paths/selection",
        json={"learning_path_id": 12},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert list_response.status_code == 401
    assert select_response.status_code == 401


def test_list_returns_the_enrolments_and_no_selection() -> None:
    harness = harness_with(ALGORITHMS, DATABASES)
    login(harness)

    response = harness.client.get("/api/learning-paths")

    assert response.status_code == 200
    assert response.json() == {
        "learning_path_id": None,
        "learning_paths": [
            {
                "id": 12,
                "title": "Algorithms",
                "short_title": "186.813",
                "url": "https://tu.test/12",
            },
            {"id": 34, "title": "Databases", "short_title": "184.686", "url": None},
        ],
    }


def test_list_is_empty_when_there_is_nothing_to_select() -> None:
    harness = harness_with()
    login(harness)

    response = harness.client.get("/api/learning-paths")

    assert response.status_code == 200
    assert response.json() == {"learning_path_id": None, "learning_paths": []}


def test_list_reports_an_unreachable_source_as_a_bad_gateway() -> None:
    harness = harness_with(error=MoodleError("down"))
    login(harness)

    response = harness.client.get("/api/learning-paths")

    assert response.status_code == 502


def test_selecting_an_enrolment_scopes_the_session_to_it() -> None:
    harness = harness_with(ALGORITHMS, DATABASES)
    login(harness)

    response = harness.client.put(
        "/api/learning-paths/selection",
        json={"learning_path_id": 34},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {"learning_path_id": 34}
    assert session_learning_path(harness) == "34"
    assert harness.client.get("/api/learning-paths").json()["learning_path_id"] == 34


def test_selection_can_be_changed_again() -> None:
    harness = harness_with(ALGORITHMS, DATABASES, tenant=SessionTenant(learning_path_id="12"))
    login(harness)

    response = harness.client.put(
        "/api/learning-paths/selection",
        json={"learning_path_id": 34},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert session_learning_path(harness) == "34"


def test_selecting_a_learning_path_outside_the_enrolments_is_refused() -> None:
    harness = harness_with(ALGORITHMS, DATABASES)
    login(harness)

    response = harness.client.put(
        "/api/learning-paths/selection",
        json={"learning_path_id": 99},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 404
    assert session_learning_path(harness) is None


def test_selection_requires_csrf() -> None:
    harness = harness_with(ALGORITHMS, DATABASES)
    login(harness)

    response = harness.client.put("/api/learning-paths/selection", json={"learning_path_id": 12})

    assert response.status_code == 403
    assert session_learning_path(harness) is None


@pytest.mark.parametrize("body", [{"learning_path_id": 0}, {"learning_path_id": "abc"}, {}])
def test_selection_validates_the_id(body: dict[str, object]) -> None:
    harness = harness_with(ALGORITHMS)
    login(harness)

    response = harness.client.put(
        "/api/learning-paths/selection", json=body, headers=csrf_headers(harness)
    )

    assert response.status_code == 422


def test_login_selects_the_only_enrolment() -> None:
    harness = harness_with(ALGORITHMS)

    login(harness)

    assert session_learning_path(harness) == "12"


@pytest.mark.parametrize("courses", [(), (ALGORITHMS, DATABASES)], ids=["none", "several"])
def test_login_selects_nothing_unless_there_is_exactly_one_enrolment(
    courses: tuple[Course, ...],
) -> None:
    harness = harness_with(*courses)

    login(harness)

    assert session_learning_path(harness) is None


def test_login_survives_an_enrolment_lookup_that_fails() -> None:
    harness = harness_with(error=MoodleError("down"))

    login(harness)

    assert session_learning_path(harness) is None


def test_login_keeps_a_selection_the_authenticator_already_made() -> None:
    harness = harness_with(ALGORITHMS, DATABASES, tenant=SessionTenant(learning_path_id="34"))

    login(harness)

    assert session_learning_path(harness) == "34"


# --- A fresh real login, against the real database ---------------------------
#
# These go through POST /api/auth/login with the production
# default_login_authenticator. Only login_both, the TUWEL/TISS SAML round trip,
# is stubbed: no seeded tenant, no e2e auth bypass, no numeric cookie — the
# three things that hid #106 in the first place.


@pytest.fixture
def tuwel_sso(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_login_both(
        tuwel_host: str,
        _tiss_host: str,
        _username: str,
        _password: str,
        _mfa_code: str | None = None,
    ) -> tuple[SessionCredentials, None]:
        credentials = SessionCredentials(
            moodle_session="moodle-session",
            sesskey="sesskey",
            host=tuwel_host,
            created_at="2026-09-26T10:00:00Z",
        )
        return credentials, None

    monkeypatch.setattr(auth_router, "login_both", fake_login_both)


async def start_session(harness: DbHarness, learning_path_id: int) -> int:
    response = await harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": learning_path_id, "topic": "Graphs"},
        headers=harness.csrf_headers(),
    )
    return response.status_code


@pytest.mark.postgres
@pytest.mark.usefixtures("tuwel_sso")
async def test_fresh_login_with_one_enrolment_can_start_a_study_session(
    clean_engine: AsyncEngine,
) -> None:
    moodle = FakeMoodle(courses=[ALGORITHMS])
    async with db_harness(clean_engine, moodle=moodle, real_login=True) as harness:
        await harness.login("e12345678")

        assert await start_session(harness, 12) == 200
        sessions = await harness.client.get("/api/study/sessions?learning_path_id=12")
        assert [s["topic"] for s in sessions.json()["sessions"]] == ["Graphs"]


@pytest.mark.postgres
@pytest.mark.usefixtures("tuwel_sso")
async def test_fresh_login_with_several_enrolments_starts_after_picking_one(
    clean_engine: AsyncEngine,
) -> None:
    moodle = FakeMoodle(courses=[ALGORITHMS, DATABASES])
    async with db_harness(clean_engine, moodle=moodle, real_login=True) as harness:
        await harness.login("e12345678")

        assert await start_session(harness, 34) == 403
        listed = await harness.client.get("/api/learning-paths")
        assert listed.json()["learning_path_id"] is None
        assert [path["id"] for path in listed.json()["learning_paths"]] == [12, 34]

        selected = await harness.client.put(
            "/api/learning-paths/selection",
            json={"learning_path_id": 34},
            headers=harness.csrf_headers(),
        )
        assert selected.status_code == 200
        assert await start_session(harness, 34) == 200
