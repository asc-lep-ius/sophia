"""Chronos history API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sophia.api.routers import chronos_history as chronos_history_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import CalibrationMetrics, Deadline, DeadlineType
from sophia.services.chronos_history import DayEffort, DeadlineReflection, TimeEntry

from ._session_helpers import build_harness, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


class FakeDeadlineCursor:
    def __init__(self, row: tuple[int] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[int] | None:
        return self._row


class FakeDeadlineDb:
    def __init__(self, deadline_courses: dict[str, int]) -> None:
        self._deadline_courses = deadline_courses

    async def execute(self, _query: str, parameters: tuple[str]) -> FakeDeadlineCursor:
        course_id = self._deadline_courses.get(parameters[0])
        return FakeDeadlineCursor(None if course_id is None else (course_id,))


def course_tenant(course_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        course_id=str(course_id),
        cohort_id="cohort-a",
        role="student",
    )


def sample_deadline() -> Deadline:
    return Deadline(
        id="assign:1",
        name="Homework 1",
        course_id=12,
        course_name="Algorithms",
        deadline_type=DeadlineType.ASSIGNMENT,
        due_at=datetime(2026, 5, 1, 10, tzinfo=UTC),
    )


def test_chronos_history_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    deadlines_response = harness.client.get("/api/chronos-history/deadlines?course_id=12")
    reflection_response = harness.client.get("/api/chronos-history/deadlines/assign:1/reflection")
    time_response = harness.client.get("/api/chronos-history/deadlines/assign:1/time-entries")
    effort_response = harness.client.get("/api/chronos-history/effort-distribution?course_id=12")
    calibration_response = harness.client.get("/api/chronos-history/calibration?course_id=12")

    assert deadlines_response.status_code == 401
    assert reflection_response.status_code == 401
    assert time_response.status_code == 401
    assert effort_response.status_code == 401
    assert calibration_response.status_code == 401


def test_chronos_history_routes_return_response_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_get_past_deadlines(
        db: object,
        *,
        course_id: int | None = None,
        limit: int = 50,
    ) -> list[Deadline]:
        assert db is fake_app.db
        assert course_id == 12
        assert limit == 25
        return [sample_deadline()]

    async def fake_get_deadline_reflection(
        db: object,
        deadline_id: str,
    ) -> DeadlineReflection | None:
        assert db is fake_app.db
        assert deadline_id == "assign:1"
        return DeadlineReflection(
            predicted_hours=2.0,
            actual_hours=3.0,
            reflection_text="Need smaller chunks.",
            reflected_at="2026-05-02T10:00:00Z",
        )

    async def fake_get_time_entries(db: object, deadline_id: str) -> list[TimeEntry]:
        assert db is fake_app.db
        assert deadline_id == "assign:1"
        return [
            TimeEntry(
                hours=1.5,
                source="manual",
                note="Reading proofs",
                recorded_at="2026-05-01T09:00:00Z",
            ),
        ]

    async def fake_get_effort_distribution(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> list[DayEffort]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 14
        return [
            DayEffort(
                date="2026-05-30",
                deadline_efforts={"Homework 1": 1.5},
                unestimated=["Lab"],
                total=1.5,
            ),
        ]

    async def fake_get_calibration_metrics(
        db: object,
        *,
        course_id: int | None = None,
    ) -> list[CalibrationMetrics]:
        assert db is fake_app.db
        assert course_id == 12
        return [
            CalibrationMetrics(
                domain="effort:assignment",
                sample_count=3,
                mean_error=0.25,
                mean_absolute_error=0.5,
                trend="improving",
            ),
        ]

    monkeypatch.setattr(chronos_history_router, "get_past_deadlines", fake_get_past_deadlines)
    monkeypatch.setattr(
        chronos_history_router,
        "get_deadline_reflection",
        fake_get_deadline_reflection,
    )
    monkeypatch.setattr(chronos_history_router, "get_time_entries", fake_get_time_entries)
    monkeypatch.setattr(
        chronos_history_router,
        "get_effort_distribution",
        fake_get_effort_distribution,
    )
    monkeypatch.setattr(
        chronos_history_router,
        "get_calibration_metrics",
        fake_get_calibration_metrics,
    )

    deadlines_response = harness.client.get("/api/chronos-history/deadlines?course_id=12&limit=25")
    reflection_response = harness.client.get("/api/chronos-history/deadlines/assign:1/reflection")
    time_response = harness.client.get("/api/chronos-history/deadlines/assign:1/time-entries")
    effort_response = harness.client.get("/api/chronos-history/effort-distribution?course_id=12")
    calibration_response = harness.client.get("/api/chronos-history/calibration?course_id=12")

    assert deadlines_response.status_code == 200
    assert deadlines_response.json()["deadlines"][0] == {
        "id": "assign:1",
        "name": "Homework 1",
        "course_id": 12,
        "course_name": "Algorithms",
        "deadline_type": "assignment",
        "due_at": "2026-05-01T10:00:00Z",
        "grade_weight": None,
        "submission_status": None,
        "url": None,
        "extra": {},
    }
    assert reflection_response.json() == {
        "deadline_id": "assign:1",
        "reflection": {
            "predicted_hours": 2.0,
            "actual_hours": 3.0,
            "reflection_text": "Need smaller chunks.",
            "reflected_at": "2026-05-02T10:00:00Z",
        },
    }
    assert time_response.json() == {
        "deadline_id": "assign:1",
        "entries": [
            {
                "hours": 1.5,
                "source": "manual",
                "note": "Reading proofs",
                "recorded_at": "2026-05-01T09:00:00Z",
            },
        ],
    }
    assert effort_response.json() == {
        "course_id": 12,
        "horizon_days": 14,
        "days": [
            {
                "date": "2026-05-30",
                "deadline_efforts": {"Homework 1": 1.5},
                "unestimated": ["Lab"],
                "total": 1.5,
            },
        ],
    }
    assert calibration_response.json() == {
        "course_id": 12,
        "metrics": [
            {
                "domain": "effort:assignment",
                "sample_count": 3,
                "mean_error": 0.25,
                "mean_absolute_error": 0.5,
                "trend": "improving",
            },
        ],
    }


def test_chronos_history_optional_course_routes_use_session_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)
    course_ids: list[int | None] = []

    async def fake_get_past_deadlines(
        db: object,
        *,
        course_id: int | None = None,
        limit: int = 50,
    ) -> list[Deadline]:
        assert db is fake_app.db
        assert limit == 50
        course_ids.append(course_id)
        return [sample_deadline()]

    async def fake_get_effort_distribution(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> list[DayEffort]:
        assert db is fake_app.db
        assert horizon_days == 14
        course_ids.append(course_id)
        return []

    async def fake_get_calibration_metrics(
        db: object,
        *,
        course_id: int | None = None,
    ) -> list[CalibrationMetrics]:
        assert db is fake_app.db
        course_ids.append(course_id)
        return []

    monkeypatch.setattr(chronos_history_router, "get_past_deadlines", fake_get_past_deadlines)
    monkeypatch.setattr(
        chronos_history_router,
        "get_effort_distribution",
        fake_get_effort_distribution,
    )
    monkeypatch.setattr(
        chronos_history_router,
        "get_calibration_metrics",
        fake_get_calibration_metrics,
    )

    deadlines_response = harness.client.get("/api/chronos-history/deadlines")
    effort_response = harness.client.get("/api/chronos-history/effort-distribution")
    calibration_response = harness.client.get("/api/chronos-history/calibration")

    assert deadlines_response.status_code == 200
    assert effort_response.status_code == 200
    assert calibration_response.status_code == 200
    assert deadlines_response.json()["course_id"] == 12
    assert effort_response.json()["course_id"] == 12
    assert calibration_response.json()["course_id"] == 12
    assert course_ids == [12, 12, 12]


def test_chronos_history_reflection_missing_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_get_deadline_reflection(
        _db: object,
        _deadline_id: str,
    ) -> DeadlineReflection | None:
        return None

    monkeypatch.setattr(
        chronos_history_router,
        "get_deadline_reflection",
        fake_get_deadline_reflection,
    )

    response = harness.client.get("/api/chronos-history/deadlines/assign:1/reflection")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_chronos_history_deadline_missing_returns_404() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=FakeDeadlineDb({}))),
        tenant=course_tenant(),
    )
    login(harness)

    response = harness.client.get("/api/chronos-history/deadlines/assign:404/time-entries")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_chronos_history_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    deadlines_response = harness.client.get("/api/chronos-history/deadlines?course_id=0")
    limited_response = harness.client.get("/api/chronos-history/deadlines?course_id=12&limit=0")
    effort_response = harness.client.get(
        "/api/chronos-history/effort-distribution?course_id=12&horizon_days=0"
    )

    assert deadlines_response.status_code == 422
    assert limited_response.status_code == 422
    assert effort_response.status_code == 422
    assert deadlines_response.json() == {
        "detail": {"code": "request.validation_failed", "params": {}}
    }


def test_chronos_history_routes_reject_out_of_scope_course_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_past_deadlines(
        _db: object,
        *,
        course_id: int | None = None,
        limit: int = 50,
    ) -> list[Deadline]:
        calls.append(f"deadlines:{course_id}:{limit}")
        return []

    monkeypatch.setattr(chronos_history_router, "get_past_deadlines", fake_get_past_deadlines)

    deadlines_response = harness.client.get("/api/chronos-history/deadlines?course_id=99")
    effort_response = harness.client.get("/api/chronos-history/effort-distribution?course_id=99")
    calibration_response = harness.client.get("/api/chronos-history/calibration?course_id=99")

    assert deadlines_response.status_code == 403
    assert effort_response.status_code == 403
    assert calibration_response.status_code == 403
    assert calls == []


def test_chronos_history_deadline_paths_reject_cross_course_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 99}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_time_entries(_db: object, deadline_id: str) -> list[TimeEntry]:
        calls.append(deadline_id)
        return []

    monkeypatch.setattr(chronos_history_router, "get_time_entries", fake_get_time_entries)

    response = harness.client.get("/api/chronos-history/deadlines/assign:1/time-entries")

    assert response.status_code == 403
    assert calls == []


def test_chronos_history_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/chronos-history/deadlines"]["get"]["tags"] == [
        "chronos-history",
    ]
    assert openapi["paths"]["/api/chronos-history/deadlines"]["get"]["operationId"] == (
        "listChronosHistoryDeadlines"
    )
    assert (
        openapi["paths"]["/api/chronos-history/deadlines/{deadline_id}/reflection"]["get"][
            "operationId"
        ]
        == "getChronosHistoryReflection"
    )
    assert (
        openapi["paths"]["/api/chronos-history/deadlines/{deadline_id}/time-entries"]["get"][
            "operationId"
        ]
        == "listChronosHistoryTimeEntries"
    )
    assert (
        openapi["paths"]["/api/chronos-history/effort-distribution"]["get"]["operationId"]
        == "getChronosHistoryEffortDistribution"
    )
    assert openapi["paths"]["/api/chronos-history/calibration"]["get"]["operationId"] == (
        "getChronosHistoryCalibration"
    )
