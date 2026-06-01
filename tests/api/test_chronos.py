"""Chronos current-state API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sophia.api.routers import chronos as chronos_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import Deadline, DeadlineType, EffortEstimate, EstimationScaffold

from ._session_helpers import build_harness, csrf_headers, login

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


def sample_deadline(deadline_id: str = "assign:1", course_id: int = 12) -> Deadline:
    return Deadline(
        id=deadline_id,
        name="Homework 1",
        course_id=course_id,
        course_name="Algorithms",
        deadline_type=DeadlineType.ASSIGNMENT,
        due_at=datetime(2026, 6, 1, 10, tzinfo=UTC),
        grade_weight=0.2,
        submission_status="not_submitted",
        url="https://tu.test/assign/1",
        extra={"points": 10},
    )


def test_chronos_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    deadlines_response = harness.client.get("/api/chronos/deadlines?course_id=12")
    sync_response = harness.client.post(
        "/api/chronos/sync",
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    estimate_response = harness.client.post(
        "/api/chronos/estimates",
        json={"course_id": 12, "deadline_id": "assign:1", "predicted_hours": 3.5},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    timer_response = harness.client.post(
        "/api/chronos/timers/assign:1/start",
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    tracked_response = harness.client.get("/api/chronos/deadlines/assign:1/tracked-time")

    assert deadlines_response.status_code == 401
    assert sync_response.status_code == 401
    assert estimate_response.status_code == 401
    assert timer_response.status_code == 401
    assert tracked_response.status_code == 401


def test_chronos_current_state_routes_return_response_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 12, "exam:1": 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_deadlines(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> list[Deadline]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 14
        return [sample_deadline()]

    async def fake_sync_deadlines(app: AppContainer) -> list[Deadline]:
        assert app is fake_app
        calls.append("sync")
        return [sample_deadline()]

    async def fake_start_timer(db: object, deadline_id: str) -> None:
        assert db is fake_app.db
        calls.append(f"start:{deadline_id}")

    async def fake_stop_timer(db: object, deadline_id: str) -> float:
        assert db is fake_app.db
        calls.append(f"stop:{deadline_id}")
        return 1.25

    async def fake_get_tracked_time(db: object, deadline_id: str) -> float:
        assert db is fake_app.db
        calls.append(f"tracked:{deadline_id}")
        return 2.5

    async def fake_record_time(
        db: object,
        deadline_id: str,
        hours: float,
        note: str | None = None,
        *,
        recorded_at: str | None = None,
    ) -> None:
        assert db is fake_app.db
        assert hours == 1.5
        assert note == "Reading proofs"
        assert recorded_at == "2026-05-29T09:00:00Z"
        calls.append(f"time:{deadline_id}")

    async def fake_record_reflection(
        db: object,
        deadline_id: str,
        *,
        predicted_hours: float | None,
        actual_hours: float,
        reflection_text: str,
    ) -> None:
        assert db is fake_app.db
        assert predicted_hours == 2.0
        assert actual_hours == 3.0
        assert reflection_text == "Need smaller chunks."
        calls.append(f"reflection:{deadline_id}")

    async def fake_complete_deadline(
        app: AppContainer,
        deadline_id: str,
    ) -> tuple[float | None, float, str]:
        assert app is fake_app
        calls.append(f"complete:{deadline_id}")
        return 2.0, 3.0, "Slightly under."

    async def fake_get_workload_forecast(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> dict[str, object]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 14
        return {
            "total_estimated_hours": 4.0,
            "total_tracked_hours": 1.0,
            "remaining_hours": 3.0,
            "deadline_count": 1,
            "per_day": {"2026-05-30": [("Homework 1", 3.0)]},
        }

    async def fake_get_upcoming_exams(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 30,
    ) -> list[Deadline]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 30
        return [
            sample_deadline("exam:1", course_id=12).model_copy(
                update={"deadline_type": DeadlineType.EXAM},
            ),
        ]

    async def fake_export_deadlines_ics(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 30,
    ) -> str:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 30
        return "BEGIN:VCALENDAR\nEND:VCALENDAR"

    monkeypatch.setattr(chronos_router, "get_deadlines", fake_get_deadlines)
    monkeypatch.setattr(chronos_router, "sync_deadlines", fake_sync_deadlines)
    monkeypatch.setattr(chronos_router, "start_timer", fake_start_timer)
    monkeypatch.setattr(chronos_router, "stop_timer", fake_stop_timer)
    monkeypatch.setattr(chronos_router, "get_tracked_time", fake_get_tracked_time)
    monkeypatch.setattr(chronos_router, "record_time", fake_record_time)
    monkeypatch.setattr(chronos_router, "record_reflection", fake_record_reflection)
    monkeypatch.setattr(chronos_router, "complete_deadline", fake_complete_deadline)
    monkeypatch.setattr(chronos_router, "get_workload_forecast", fake_get_workload_forecast)
    monkeypatch.setattr(chronos_router, "get_upcoming_exams", fake_get_upcoming_exams)
    monkeypatch.setattr(chronos_router, "export_deadlines_ics", fake_export_deadlines_ics)

    deadlines_response = harness.client.get("/api/chronos/deadlines?course_id=12")
    sync_response = harness.client.post("/api/chronos/sync", headers=csrf_headers(harness))
    start_response = harness.client.post(
        "/api/chronos/timers/assign:1/start",
        headers=csrf_headers(harness),
    )
    stop_response = harness.client.post(
        "/api/chronos/timers/assign:1/stop",
        headers=csrf_headers(harness),
    )
    tracked_response = harness.client.get("/api/chronos/deadlines/assign:1/tracked-time")
    time_response = harness.client.post(
        "/api/chronos/time-entries",
        json={
            "course_id": 12,
            "deadline_id": "assign:1",
            "hours": 1.5,
            "note": "Reading proofs",
            "recorded_at": "2026-05-29T09:00:00Z",
        },
        headers=csrf_headers(harness),
    )
    reflection_response = harness.client.post(
        "/api/chronos/reflections",
        json={
            "course_id": 12,
            "deadline_id": "assign:1",
            "predicted_hours": 2.0,
            "actual_hours": 3.0,
            "reflection_text": "Need smaller chunks.",
        },
        headers=csrf_headers(harness),
    )
    completion_response = harness.client.post(
        "/api/chronos/deadlines/assign:1/complete",
        json={"course_id": 12},
        headers=csrf_headers(harness),
    )
    workload_response = harness.client.get("/api/chronos/workload?course_id=12")
    exams_response = harness.client.get("/api/chronos/upcoming-exams?course_id=12")
    ics_response = harness.client.get("/api/chronos/ics?course_id=12")

    assert deadlines_response.status_code == 200
    assert deadlines_response.json() == {
        "course_id": 12,
        "horizon_days": 14,
        "deadlines": [
            {
                "id": "assign:1",
                "name": "Homework 1",
                "course_id": 12,
                "course_name": "Algorithms",
                "deadline_type": "assignment",
                "due_at": "2026-06-01T10:00:00Z",
                "grade_weight": 0.2,
                "submission_status": "not_submitted",
                "url": "https://tu.test/assign/1",
                "extra": {"points": 10},
            },
        ],
    }
    assert sync_response.status_code == 200
    assert sync_response.json()["synced_count"] == 1
    assert start_response.json() == {"deadline_id": "assign:1", "started": True}
    assert stop_response.json() == {"deadline_id": "assign:1", "elapsed_hours": 1.25}
    assert tracked_response.json() == {"deadline_id": "assign:1", "total_hours": 2.5}
    assert time_response.json() == {"deadline_id": "assign:1", "recorded": True}
    assert reflection_response.json() == {"deadline_id": "assign:1", "recorded": True}
    assert completion_response.json() == {
        "deadline_id": "assign:1",
        "predicted_hours": 2.0,
        "actual_hours": 3.0,
        "feedback": "Slightly under.",
        "completed": True,
    }
    assert workload_response.json() == {
        "course_id": 12,
        "horizon_days": 14,
        "total_estimated_hours": 4.0,
        "total_tracked_hours": 1.0,
        "remaining_hours": 3.0,
        "deadline_count": 1,
        "per_day": [{"date": "2026-05-30", "items": [{"name": "Homework 1", "hours": 3.0}]}],
    }
    assert exams_response.status_code == 200
    assert exams_response.json()["exams"][0]["deadline_type"] == "exam"
    assert ics_response.json() == {
        "course_id": 12,
        "horizon_days": 30,
        "ics": "BEGIN:VCALENDAR\nEND:VCALENDAR",
    }
    assert calls == [
        "sync",
        "start:assign:1",
        "stop:assign:1",
        "tracked:assign:1",
        "time:assign:1",
        "reflection:assign:1",
        "complete:assign:1",
    ]


def test_chronos_current_state_uses_session_course_when_query_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_deadlines(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> list[Deadline]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 14
        calls.append("deadlines")
        return [sample_deadline()]

    async def fake_get_workload_forecast(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> dict[str, object]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 14
        calls.append("workload")
        return {
            "total_estimated_hours": 0.0,
            "total_tracked_hours": 0.0,
            "remaining_hours": 0.0,
            "deadline_count": 0,
            "per_day": {},
        }

    async def fake_get_upcoming_exams(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 30,
    ) -> list[Deadline]:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 30
        calls.append("exams")
        return []

    async def fake_export_deadlines_ics(
        db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 30,
    ) -> str:
        assert db is fake_app.db
        assert course_id == 12
        assert horizon_days == 30
        calls.append("ics")
        return "BEGIN:VCALENDAR\nEND:VCALENDAR"

    monkeypatch.setattr(chronos_router, "get_deadlines", fake_get_deadlines)
    monkeypatch.setattr(chronos_router, "get_workload_forecast", fake_get_workload_forecast)
    monkeypatch.setattr(chronos_router, "get_upcoming_exams", fake_get_upcoming_exams)
    monkeypatch.setattr(chronos_router, "export_deadlines_ics", fake_export_deadlines_ics)

    deadlines_response = harness.client.get("/api/chronos/deadlines")
    workload_response = harness.client.get("/api/chronos/workload")
    exams_response = harness.client.get("/api/chronos/upcoming-exams")
    ics_response = harness.client.get("/api/chronos/ics")

    assert deadlines_response.status_code == 200
    assert deadlines_response.json()["course_id"] == 12
    assert workload_response.status_code == 200
    assert workload_response.json()["course_id"] == 12
    assert exams_response.status_code == 200
    assert exams_response.json()["course_id"] == 12
    assert ics_response.status_code == 200
    assert ics_response.json()["course_id"] == 12
    assert calls == ["deadlines", "workload", "exams", "ics"]


def test_record_estimate_returns_saved_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_record_estimate(
        app: AppContainer,
        *,
        deadline_id: str,
        course_id: int,
        predicted_hours: float,
        breakdown: dict[str, float] | None = None,
        intention: str | None = None,
    ) -> EffortEstimate:
        assert app is fake_app
        assert deadline_id == "assign:1"
        assert course_id == 12
        assert predicted_hours == 3.5
        assert breakdown == {"reading": 1.5, "implementation": 2.0}
        assert intention == "Start after breakfast."
        return EffortEstimate(
            deadline_id=deadline_id,
            course_id=course_id,
            predicted_hours=predicted_hours,
            breakdown=breakdown,
            implementation_intention=intention,
            scaffold_level=EstimationScaffold.FULL,
            estimated_at="2026-05-29T10:00:00Z",
        )

    monkeypatch.setattr(chronos_router, "record_estimate", fake_record_estimate)

    response = harness.client.post(
        "/api/chronos/estimates",
        json={
            "course_id": 12,
            "deadline_id": "assign:1",
            "predicted_hours": 3.5,
            "breakdown": {"reading": 1.5, "implementation": 2.0},
            "intention": "Start after breakfast.",
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "estimate": {
            "deadline_id": "assign:1",
            "course_id": 12,
            "predicted_hours": 3.5,
            "breakdown": {"reading": 1.5, "implementation": 2.0},
            "implementation_intention": "Start after breakfast.",
            "scaffold_level": "full",
            "estimated_at": "2026-05-29T10:00:00Z",
        },
    }


def test_record_estimate_rejects_cross_course_deadline_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 99}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_record_estimate(
        _app: AppContainer,
        *,
        deadline_id: str,
        course_id: int,
        predicted_hours: float,
        breakdown: dict[str, float] | None = None,
        intention: str | None = None,
    ) -> EffortEstimate:
        calls.append(deadline_id)
        return EffortEstimate(
            deadline_id=deadline_id,
            course_id=course_id,
            predicted_hours=predicted_hours,
            breakdown=breakdown,
            implementation_intention=intention,
            scaffold_level=EstimationScaffold.FULL,
            estimated_at="2026-05-29T10:00:00Z",
        )

    monkeypatch.setattr(chronos_router, "record_estimate", fake_record_estimate)

    response = harness.client.post(
        "/api/chronos/estimates",
        json={"course_id": 12, "deadline_id": "assign:1", "predicted_hours": 3.5},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 403
    assert calls == []


def test_record_estimate_missing_deadline_returns_404_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_record_estimate(
        _app: AppContainer,
        *,
        deadline_id: str,
        course_id: int,
        predicted_hours: float,
        breakdown: dict[str, float] | None = None,
        intention: str | None = None,
    ) -> EffortEstimate:
        calls.append(deadline_id)
        return EffortEstimate(
            deadline_id=deadline_id,
            course_id=course_id,
            predicted_hours=predicted_hours,
            breakdown=breakdown,
            implementation_intention=intention,
            scaffold_level=EstimationScaffold.FULL,
            estimated_at="2026-05-29T10:00:00Z",
        )

    monkeypatch.setattr(chronos_router, "record_estimate", fake_record_estimate)

    response = harness.client.post(
        "/api/chronos/estimates",
        json={"course_id": 12, "deadline_id": "assign:404", "predicted_hours": 3.5},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}
    assert calls == []


def test_chronos_filtered_deadline_lookup_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_get_deadlines(
        _db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> list[Deadline]:
        return []

    monkeypatch.setattr(chronos_router, "get_deadlines", fake_get_deadlines)

    response = harness.client.get("/api/chronos/deadlines?course_id=12&deadline_type=quiz")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_chronos_path_deadline_missing_returns_404() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=FakeDeadlineDb({}))),
        tenant=course_tenant(),
    )
    login(harness)

    response = harness.client.get("/api/chronos/deadlines/assign:404/tracked-time")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_chronos_mutating_routes_require_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    sync_response = harness.client.post("/api/chronos/sync")
    estimate_response = harness.client.post(
        "/api/chronos/estimates",
        json={"course_id": 12, "deadline_id": "assign:1", "predicted_hours": 3.5},
    )
    timer_response = harness.client.post("/api/chronos/timers/assign:1/start")
    time_response = harness.client.post(
        "/api/chronos/time-entries",
        json={"course_id": 12, "deadline_id": "assign:1", "hours": 1.5},
    )
    reflection_response = harness.client.post(
        "/api/chronos/reflections",
        json={
            "course_id": 12,
            "deadline_id": "assign:1",
            "actual_hours": 3.0,
            "reflection_text": "Need smaller chunks.",
        },
    )
    complete_response = harness.client.post(
        "/api/chronos/deadlines/assign:1/complete",
        json={"course_id": 12},
    )

    assert sync_response.status_code == 403
    assert estimate_response.status_code == 403
    assert timer_response.status_code == 403
    assert time_response.status_code == 403
    assert reflection_response.status_code == 403
    assert complete_response.status_code == 403


def test_chronos_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    deadlines_response = harness.client.get("/api/chronos/deadlines?course_id=0")
    workload_response = harness.client.get("/api/chronos/workload?course_id=12&horizon_days=0")
    estimate_response = harness.client.post(
        "/api/chronos/estimates",
        json={"course_id": 12, "deadline_id": "assign:1", "predicted_hours": 0},
        headers=csrf_headers(harness),
    )
    time_response = harness.client.post(
        "/api/chronos/time-entries",
        json={"course_id": 12, "deadline_id": "assign:1", "hours": 0},
        headers=csrf_headers(harness),
    )

    assert deadlines_response.status_code == 422
    assert workload_response.status_code == 422
    assert estimate_response.status_code == 422
    assert time_response.status_code == 422
    assert deadlines_response.json() == {
        "detail": {"code": "request.validation_failed", "params": {}}
    }


def test_chronos_routes_reject_out_of_scope_course_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_deadlines(
        _db: object,
        *,
        course_id: int | None = None,
        horizon_days: int = 14,
    ) -> list[Deadline]:
        calls.append(f"deadlines:{course_id}:{horizon_days}")
        return []

    async def fake_record_estimate(
        _app: AppContainer,
        *,
        deadline_id: str,
        course_id: int,
        predicted_hours: float,
        breakdown: dict[str, float] | None = None,
        intention: str | None = None,
    ) -> EffortEstimate:
        calls.append(deadline_id)
        return EffortEstimate(
            deadline_id=deadline_id,
            course_id=course_id,
            predicted_hours=predicted_hours,
            scaffold_level=EstimationScaffold.FULL,
            estimated_at="2026-05-29T10:00:00Z",
        )

    monkeypatch.setattr(chronos_router, "get_deadlines", fake_get_deadlines)
    monkeypatch.setattr(chronos_router, "record_estimate", fake_record_estimate)

    deadlines_response = harness.client.get("/api/chronos/deadlines?course_id=99")
    estimate_response = harness.client.post(
        "/api/chronos/estimates",
        json={"course_id": 99, "deadline_id": "assign:1", "predicted_hours": 3.5},
        headers=csrf_headers(harness),
    )

    assert deadlines_response.status_code == 403
    assert estimate_response.status_code == 403
    assert calls == []


def test_chronos_deadline_paths_reject_cross_course_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeDeadlineDb({"assign:1": 99}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_start_timer(_db: object, deadline_id: str) -> None:
        calls.append(deadline_id)

    monkeypatch.setattr(chronos_router, "start_timer", fake_start_timer)

    response = harness.client.post(
        "/api/chronos/timers/assign:1/start",
        headers=csrf_headers(harness),
    )

    assert response.status_code == 403
    assert calls == []


def test_chronos_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/chronos/deadlines"]["get"]["tags"] == ["chronos"]
    assert openapi["paths"]["/api/chronos/deadlines"]["get"]["operationId"] == (
        "listChronosDeadlines"
    )
    assert openapi["paths"]["/api/chronos/sync"]["post"]["operationId"] == ("syncChronosDeadlines")
    assert openapi["paths"]["/api/chronos/estimates"]["post"]["operationId"] == (
        "recordChronosEstimate"
    )
    assert (
        openapi["paths"]["/api/chronos/timers/{deadline_id}/start"]["post"]["operationId"]
        == "startChronosTimer"
    )
    assert (
        openapi["paths"]["/api/chronos/timers/{deadline_id}/stop"]["post"]["operationId"]
        == "stopChronosTimer"
    )
    assert (
        openapi["paths"]["/api/chronos/deadlines/{deadline_id}/tracked-time"]["get"]["operationId"]
        == "getChronosTrackedTime"
    )
    assert openapi["paths"]["/api/chronos/time-entries"]["post"]["operationId"] == (
        "recordChronosTimeEntry"
    )
    assert openapi["paths"]["/api/chronos/reflections"]["post"]["operationId"] == (
        "recordChronosReflection"
    )
    assert (
        openapi["paths"]["/api/chronos/deadlines/{deadline_id}/complete"]["post"]["operationId"]
        == "completeChronosDeadline"
    )
    assert openapi["paths"]["/api/chronos/workload"]["get"]["operationId"] == ("getChronosWorkload")
    assert openapi["paths"]["/api/chronos/upcoming-exams"]["get"]["operationId"] == (
        "listChronosUpcomingExams"
    )
    assert openapi["paths"]["/api/chronos/ics"]["get"]["operationId"] == "exportChronosIcs"
