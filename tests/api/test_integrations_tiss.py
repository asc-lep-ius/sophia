"""TISS registration integration API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.api.routers import integrations_tiss as tiss_router
from sophia.domain.models import (
    FavoriteCourse,
    RegistrationGroup,
    RegistrationResult,
    RegistrationStatus,
    RegistrationTarget,
    RegistrationType,
    TissExamDate,
)
from sophia.services.tiss_registration import (
    FavoritesResult,
    GroupsResult,
    RegisterResult,
    StatusResult,
)

from ._session_helpers import ApiHarness, build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer

COURSE_NUMBER = "186.813"
SEMESTER = "2026S"


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


def _harness() -> ApiHarness:
    return build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))


def _favorite() -> FavoriteCourse:
    return FavoriteCourse(
        course_number=COURSE_NUMBER,
        title="Algorithmen und Datenstrukturen",
        course_type="VU",
        semester=SEMESTER,
        hours=4.0,
        ects=6.0,
        lva_registered=True,
    )


def _group() -> RegistrationGroup:
    return RegistrationGroup(
        group_id="group-1",
        name="Gruppe 1",
        day="Mo",
        time_start="10:00",
        time_end="12:00",
        location="Freihaus",
        capacity=30,
        enrolled=12,
        status=RegistrationStatus.OPEN,
    )


def test_tiss_routes_require_authentication() -> None:
    harness = _harness()

    favorites_response = harness.client.get("/api/integrations/tiss/registration/favorites")
    target_response = harness.client.get(
        f"/api/integrations/tiss/registration/targets/{COURSE_NUMBER}"
    )
    groups_response = harness.client.get(
        f"/api/integrations/tiss/registration/targets/{COURSE_NUMBER}/groups"
    )
    attempt_response = harness.client.post(
        "/api/integrations/tiss/registration/attempts",
        json={"course_number": COURSE_NUMBER},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert favorites_response.status_code == 401
    assert target_response.status_code == 401
    assert groups_response.status_code == 401
    assert attempt_response.status_code == 401


def test_list_favorites_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    login(harness)

    async def fake_get_favorites(_app: AppContainer, *, semester: str = "") -> FavoritesResult:
        assert semester == SEMESTER
        return FavoritesResult(status="success", favorites=[_favorite()])

    monkeypatch.setattr(tiss_router, "get_favorites", fake_get_favorites)

    response = harness.client.get(
        f"/api/integrations/tiss/registration/favorites?semester={SEMESTER}"
    )

    assert response.status_code == 200
    assert response.json() == {
        "connection": "connected",
        "semester": SEMESTER,
        "favorites": [
            {
                "course_number": COURSE_NUMBER,
                "title": "Algorithmen und Datenstrukturen",
                "course_type": "VU",
                "semester": SEMESTER,
                "hours": 4.0,
                "ects": 6.0,
                "lva_registered": True,
                "group_registered": False,
                "exam_registered": False,
            },
        ],
    }


def test_missing_tiss_session_is_reported_as_connection_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    login(harness)

    async def fake_get_favorites(_app: AppContainer, *, semester: str = "") -> FavoritesResult:
        return FavoritesResult(status="no_session")

    monkeypatch.setattr(tiss_router, "get_favorites", fake_get_favorites)

    response = harness.client.get("/api/integrations/tiss/registration/favorites")

    assert response.status_code == 200
    assert response.json()["connection"] == "session_missing"
    assert response.json()["favorites"] == []


def test_expired_tiss_session_is_reported_as_connection_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    login(harness)

    async def fake_get_registration_status(
        _app: AppContainer,
        _course_number: str,
        _semester: str,
    ) -> StatusResult:
        return StatusResult(status="auth_expired")

    monkeypatch.setattr(tiss_router, "get_registration_status", fake_get_registration_status)

    response = harness.client.get(
        f"/api/integrations/tiss/registration/targets/{COURSE_NUMBER}?semester={SEMESTER}"
    )

    assert response.status_code == 200
    assert response.json() == {
        "connection": "session_expired",
        "course_number": COURSE_NUMBER,
        "semester": SEMESTER,
        "target": None,
    }


def test_upstream_tiss_failure_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    login(harness)

    async def fake_get_groups(
        _app: AppContainer,
        _course_number: str,
        _semester: str,
    ) -> GroupsResult:
        return GroupsResult(status="network_error", error_message="connection reset")

    monkeypatch.setattr(tiss_router, "get_groups", fake_get_groups)

    response = harness.client.get(
        f"/api/integrations/tiss/registration/targets/{COURSE_NUMBER}/groups"
    )

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "tiss.failed", "params": {}}}


def test_registration_target_returns_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    login(harness)

    async def fake_get_registration_status(
        _app: AppContainer,
        course_number: str,
        semester: str,
    ) -> StatusResult:
        return StatusResult(
            status="success",
            target=RegistrationTarget(
                course_number=course_number,
                semester=semester,
                registration_type=RegistrationType.GROUP,
                title="Algorithmen und Datenstrukturen",
                registration_start="01.09.2026 09:00",
                status=RegistrationStatus.OPEN,
                groups=[_group()],
            ),
        )

    monkeypatch.setattr(tiss_router, "get_registration_status", fake_get_registration_status)

    response = harness.client.get(
        f"/api/integrations/tiss/registration/targets/{COURSE_NUMBER}?semester={SEMESTER}"
    )

    assert response.status_code == 200
    target = response.json()["target"]
    assert target["registration_type"] == "group"
    assert target["status"] == "open"
    assert target["groups"] == [
        {
            "group_id": "group-1",
            "name": "Gruppe 1",
            "day": "Mo",
            "time_start": "10:00",
            "time_end": "12:00",
            "location": "Freihaus",
            "capacity": 30,
            "enrolled": 12,
            "status": "open",
        },
    ]


def test_registration_attempt_requires_csrf() -> None:
    harness = _harness()
    login(harness)

    response = harness.client.post(
        "/api/integrations/tiss/registration/attempts",
        json={"course_number": COURSE_NUMBER},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_registration_attempt_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    login(harness)
    calls: list[tuple[str, str, str | None]] = []

    async def fake_register_course(
        _app: AppContainer,
        course_number: str,
        semester: str,
        *,
        group_id: str | None = None,
    ) -> RegisterResult:
        calls.append((course_number, semester, group_id))
        return RegisterResult(
            status="success",
            registration_result=RegistrationResult(
                course_number=course_number,
                registration_type=RegistrationType.GROUP,
                success=True,
                group_name="Gruppe 1",
                message="Registered",
                attempted_at="2026-08-28T09:00:00Z",
            ),
        )

    monkeypatch.setattr(tiss_router, "register_course", fake_register_course)

    response = harness.client.post(
        "/api/integrations/tiss/registration/attempts",
        json={"course_number": COURSE_NUMBER, "semester": SEMESTER, "group_id": "group-1"},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert calls == [(COURSE_NUMBER, SEMESTER, "group-1")]
    assert response.json() == {
        "connection": "connected",
        "course_number": COURSE_NUMBER,
        "semester": SEMESTER,
        "result": {
            "course_number": COURSE_NUMBER,
            "registration_type": "group",
            "success": True,
            "group_name": "Gruppe 1",
            "message": "Registered",
            "attempted_at": "2026-08-28T09:00:00Z",
        },
    }


def test_registration_attempt_validation_returns_422() -> None:
    harness = _harness()
    login(harness)

    response = harness.client.post(
        "/api/integrations/tiss/registration/attempts",
        json={"course_number": ""},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_exam_dates_return_public_api_results(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    login(harness)

    async def fake_get_exam_dates(_app: AppContainer, course_number: str) -> list[TissExamDate]:
        return [
            TissExamDate(
                exam_id="exam-1",
                course_number=course_number,
                title="Klausur",
                date_start="2026-09-01T09:00:00",
                mode="WRITTEN",
            ),
        ]

    monkeypatch.setattr(tiss_router, "get_exam_dates", fake_get_exam_dates)

    response = harness.client.get(
        f"/api/integrations/tiss/registration/targets/{COURSE_NUMBER}/exam-dates"
    )

    assert response.status_code == 200
    assert response.json()["exams"][0]["exam_id"] == "exam-1"


def test_tiss_openapi_contract_is_visible() -> None:
    harness = _harness()

    paths = harness.app.openapi()["paths"]
    favorites = paths["/api/integrations/tiss/registration/favorites"]["get"]

    assert favorites["tags"] == ["integrations-tiss"]
    assert favorites["operationId"] == "listTissFavorites"
    assert (
        paths["/api/integrations/tiss/registration/attempts"]["post"]["operationId"]
        == "createTissRegistrationAttempt"
    )


def test_malformed_course_number_is_rejected_before_the_upstream_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    login(harness)
    calls: list[str] = []

    async def fake_get_exam_dates(_app: AppContainer, course_number: str) -> list[TissExamDate]:
        calls.append(course_number)
        return []

    monkeypatch.setattr(tiss_router, "get_exam_dates", fake_get_exam_dates)

    response = harness.client.get("/api/integrations/tiss/registration/targets/%3Fq%3D1/exam-dates")

    assert response.status_code == 422
    assert calls == []


def test_alphanumeric_course_number_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """104.A32 is a real TISS shape; the adapter's own parser accepts it."""
    harness = _harness()
    login(harness)
    calls: list[str] = []

    async def fake_get_exam_dates(_app: AppContainer, course_number: str) -> list[TissExamDate]:
        calls.append(course_number)
        return []

    monkeypatch.setattr(tiss_router, "get_exam_dates", fake_get_exam_dates)

    response = harness.client.get("/api/integrations/tiss/registration/targets/104.A32/exam-dates")

    assert response.status_code == 200
    assert calls == ["104.A32"]


def test_registration_attempt_rejects_malformed_course_number() -> None:
    harness = _harness()
    login(harness)

    response = harness.client.post(
        "/api/integrations/tiss/registration/attempts",
        json={"course_number": "186813", "semester": SEMESTER},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}
