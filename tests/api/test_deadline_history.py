"""Chronos history API route tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sophia.api.routers import deadline_history as deadline_history_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import CalibrationMetrics, Deadline, DeadlineType
from sophia.services.chronos_history import DayEffort, DeadlineReflection, TimeEntry

from ._session_helpers import FakeAppContainer, build_harness, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


class FakeDeadlineDb:
    """Answers the one scalar lookup the route makes: deadline id -> course id."""

    def __init__(self, deadline_courses: dict[str, int]) -> None:
        self._deadline_courses = deadline_courses

    async def scalar(self, statement: object) -> int | None:
        deadline_id = statement.whereclause.right.value  # pyright: ignore[reportAttributeAccessIssue]
        return self._deadline_courses.get(deadline_id)


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        learning_path_id=str(learning_path_id),
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


def test_deadline_history_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    deadlines_response = harness.client.get("/api/deadline-history?learning_path_id=12")
    reflection_response = harness.client.get("/api/deadline-history/assign:1/reflection")
    time_response = harness.client.get("/api/deadline-history/assign:1/time-entries")
    effort_response = harness.client.get(
        "/api/deadline-history/effort-distribution?learning_path_id=12"
    )
    calibration_response = harness.client.get(
        "/api/deadline-history/calibration?learning_path_id=12"
    )

    assert deadlines_response.status_code == 401
    assert reflection_response.status_code == 401
    assert time_response.status_code == 401
    assert effort_response.status_code == 401
    assert calibration_response.status_code == 401


def test_deadline_history_routes_return_response_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
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

    monkeypatch.setattr(deadline_history_router, "get_past_deadlines", fake_get_past_deadlines)
    monkeypatch.setattr(
        deadline_history_router,
        "get_deadline_reflection",
        fake_get_deadline_reflection,
    )
    monkeypatch.setattr(deadline_history_router, "get_time_entries", fake_get_time_entries)
    monkeypatch.setattr(
        deadline_history_router,
        "get_effort_distribution",
        fake_get_effort_distribution,
    )
    monkeypatch.setattr(
        deadline_history_router,
        "get_calibration_metrics",
        fake_get_calibration_metrics,
    )

    deadlines_response = harness.client.get("/api/deadline-history?learning_path_id=12&limit=25")
    reflection_response = harness.client.get("/api/deadline-history/assign:1/reflection")
    time_response = harness.client.get("/api/deadline-history/assign:1/time-entries")
    effort_response = harness.client.get(
        "/api/deadline-history/effort-distribution?learning_path_id=12"
    )
    calibration_response = harness.client.get(
        "/api/deadline-history/calibration?learning_path_id=12"
    )

    assert deadlines_response.status_code == 200
    assert deadlines_response.json()["deadlines"][0] == {
        "id": "assign:1",
        "name": "Homework 1",
        "learning_path_id": 12,
        "learning_path_name": "Algorithms",
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
        "learning_path_id": 12,
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
        "learning_path_id": 12,
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


def test_deadline_history_optional_routes_use_session_learning_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
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

    monkeypatch.setattr(deadline_history_router, "get_past_deadlines", fake_get_past_deadlines)
    monkeypatch.setattr(
        deadline_history_router,
        "get_effort_distribution",
        fake_get_effort_distribution,
    )
    monkeypatch.setattr(
        deadline_history_router,
        "get_calibration_metrics",
        fake_get_calibration_metrics,
    )

    deadlines_response = harness.client.get("/api/deadline-history")
    effort_response = harness.client.get("/api/deadline-history/effort-distribution")
    calibration_response = harness.client.get("/api/deadline-history/calibration")

    assert deadlines_response.status_code == 200
    assert effort_response.status_code == 200
    assert calibration_response.status_code == 200
    assert deadlines_response.json()["learning_path_id"] == 12
    assert effort_response.json()["learning_path_id"] == 12
    assert calibration_response.json()["learning_path_id"] == 12
    assert course_ids == [12, 12, 12]


def test_deadline_history_reflection_missing_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_deadline_reflection(
        _db: object,
        _deadline_id: str,
    ) -> DeadlineReflection | None:
        return None

    monkeypatch.setattr(
        deadline_history_router,
        "get_deadline_reflection",
        fake_get_deadline_reflection,
    )

    response = harness.client.get("/api/deadline-history/assign:1/reflection")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_deadline_history_deadline_missing_returns_404() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=FakeDeadlineDb({}))),
        tenant=learning_path_tenant(),
    )
    login(harness)

    response = harness.client.get("/api/deadline-history/assign:404/time-entries")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_deadline_history_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    deadlines_response = harness.client.get("/api/deadline-history?learning_path_id=0")
    limited_response = harness.client.get("/api/deadline-history?learning_path_id=12&limit=0")
    effort_response = harness.client.get(
        "/api/deadline-history/effort-distribution?learning_path_id=12&horizon_days=0"
    )

    assert deadlines_response.status_code == 422
    assert limited_response.status_code == 422
    assert effort_response.status_code == 422
    assert deadlines_response.json() == {
        "detail": {"code": "request.validation_failed", "params": {}}
    }


def test_deadline_history_routes_reject_out_of_scope_learning_path_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(12),
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

    monkeypatch.setattr(deadline_history_router, "get_past_deadlines", fake_get_past_deadlines)

    deadlines_response = harness.client.get("/api/deadline-history?learning_path_id=99")
    effort_response = harness.client.get(
        "/api/deadline-history/effort-distribution?learning_path_id=99"
    )
    calibration_response = harness.client.get(
        "/api/deadline-history/calibration?learning_path_id=99"
    )

    assert deadlines_response.status_code == 403
    assert effort_response.status_code == 403
    assert calibration_response.status_code == 403
    assert calls == []


def test_deadline_history_deadline_paths_reject_cross_scope_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 99}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_time_entries(_db: object, deadline_id: str) -> list[TimeEntry]:
        calls.append(deadline_id)
        return []

    monkeypatch.setattr(deadline_history_router, "get_time_entries", fake_get_time_entries)

    response = harness.client.get("/api/deadline-history/assign:1/time-entries")

    assert response.status_code == 403
    assert calls == []


def test_deadline_history_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/deadline-history"]["get"]["tags"] == [
        "deadline-history",
    ]
    assert openapi["paths"]["/api/deadline-history"]["get"]["operationId"] == ("listPastDeadlines")
    assert (
        openapi["paths"]["/api/deadline-history/{deadline_id}/reflection"]["get"]["operationId"]
        == "getDeadlineReflection"
    )
    assert (
        openapi["paths"]["/api/deadline-history/{deadline_id}/time-entries"]["get"]["operationId"]
        == "listDeadlineTimeEntries"
    )
    assert (
        openapi["paths"]["/api/deadline-history/effort-distribution"]["get"]["operationId"]
        == "getEffortDistribution"
    )
    assert openapi["paths"]["/api/deadline-history/calibration"]["get"]["operationId"] == (
        "getEffortCalibration"
    )
