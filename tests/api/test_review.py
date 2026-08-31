"""Review API route tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sophia.api.routers import review as review_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import ReviewSchedule

from ._session_helpers import FakeAppContainer, build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        learning_path_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


def test_review_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    due_response = harness.client.get("/api/review/due?learning_path_id=12")
    upcoming_response = harness.client.get("/api/review/upcoming?learning_path_id=12")
    schedule_response = harness.client.post(
        "/api/review/schedules",
        json={"learning_path_id": 12, "topic": "Graphs"},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    complete_response = harness.client.post(
        "/api/review/complete",
        json={"learning_path_id": 12, "topic": "Graphs", "score": 0.75},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert due_response.status_code == 401
    assert upcoming_response.status_code == 401
    assert schedule_response.status_code == 401
    assert complete_response.status_code == 401


def test_review_read_routes_return_response_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    schedule = ReviewSchedule(
        topic="Graphs",
        course_id=12,
        interval_index=1,
        last_reviewed_at="2026-05-25T12:00:00Z",
        next_review_at="2026-05-26T12:00:00Z",
        score_at_last_review=0.75,
        difficulty=0.4,
        stability=2.0,
        review_count=3,
    )

    async def fake_get_due_reviews(
        db: object, course_id: int | None = None
    ) -> list[ReviewSchedule]:
        assert db is fake_app.db
        assert course_id == 12
        return [schedule]

    async def fake_get_upcoming_reviews(
        db: object,
        course_id: int | None = None,
        days_ahead: int = 3,
    ) -> list[ReviewSchedule]:
        assert db is fake_app.db
        assert course_id == 12
        assert days_ahead == 5
        return [schedule]

    async def fake_get_all_schedules(db: object, course_id: int) -> list[ReviewSchedule]:
        assert db is fake_app.db
        assert course_id == 12
        return [schedule]

    monkeypatch.setattr(review_router, "get_due_reviews", fake_get_due_reviews)
    monkeypatch.setattr(review_router, "get_upcoming_reviews", fake_get_upcoming_reviews)
    monkeypatch.setattr(review_router, "get_all_schedules", fake_get_all_schedules)

    due_response = harness.client.get("/api/review/due?learning_path_id=12")
    upcoming_response = harness.client.get("/api/review/upcoming?learning_path_id=12&days_ahead=5")
    schedules_response = harness.client.get("/api/review/schedules?learning_path_id=12")

    expected_schedule = {
        "topic": "Graphs",
        "learning_path_id": 12,
        "interval_index": 1,
        "interval_days": 3,
        "last_reviewed_at": "2026-05-25T12:00:00Z",
        "next_review_at": "2026-05-26T12:00:00Z",
        "score_at_last_review": 0.75,
        "difficulty": 0.4,
        "stability": 2.0,
        "review_count": 3,
        "is_due": True,
    }
    assert due_response.status_code == 200
    assert due_response.json() == {"learning_path_id": 12, "reviews": [expected_schedule]}
    assert upcoming_response.status_code == 200
    assert upcoming_response.json() == {
        "learning_path_id": 12,
        "days_ahead": 5,
        "reviews": [expected_schedule],
    }
    assert schedules_response.status_code == 200
    assert schedules_response.json() == {"learning_path_id": 12, "schedules": [expected_schedule]}


def test_review_schedules_return_404_for_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_all_schedules(_db: object, _course_id: int) -> list[ReviewSchedule]:
        return []

    monkeypatch.setattr(review_router, "get_all_schedules", fake_get_all_schedules)

    response = harness.client.get("/api/review/schedules?learning_path_id=12&topic=Missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_schedule_review_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/review/schedules",
        json={"learning_path_id": 12, "topic": "Graphs"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_schedule_review_returns_created_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_schedule_review(db: object, topic: str, course_id: int) -> ReviewSchedule:
        assert db is fake_app.db
        assert topic == "Graphs"
        assert course_id == 12
        return ReviewSchedule(topic="Graphs", course_id=12, next_review_at="2026-05-27T12:00:00Z")

    monkeypatch.setattr(review_router, "schedule_review", fake_schedule_review)

    response = harness.client.post(
        "/api/review/schedules",
        json={"learning_path_id": 12, "topic": "Graphs"},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json()["schedule"]["topic"] == "Graphs"
    assert response.json()["schedule"]["interval_days"] == 1


def test_complete_review_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/review/complete",
        json={"learning_path_id": 12, "topic": "Graphs", "score": 0.75},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_complete_review_returns_updated_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_complete_review(
        db: object,
        topic: str,
        course_id: int,
        score: float,
    ) -> ReviewSchedule:
        assert db is fake_app.db
        assert topic == "Graphs"
        assert course_id == 12
        assert score == 0.75
        return ReviewSchedule(
            topic="Graphs",
            course_id=12,
            next_review_at="2026-05-28T12:00:00Z",
            score_at_last_review=0.75,
        )

    monkeypatch.setattr(review_router, "complete_review", fake_complete_review)

    response = harness.client.post(
        "/api/review/complete",
        json={"learning_path_id": 12, "topic": "Graphs", "score": 0.75},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json()["schedule"]["topic"] == "Graphs"
    assert response.json()["schedule"]["score_at_last_review"] == 0.75


def test_review_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    due_response = harness.client.get("/api/review/due?learning_path_id=0")
    upcoming_response = harness.client.get("/api/review/upcoming?learning_path_id=12&days_ahead=0")
    complete_response = harness.client.post(
        "/api/review/complete",
        json={"learning_path_id": 12, "topic": "Graphs", "score": 1.5},
        headers=csrf_headers(harness),
    )

    assert due_response.status_code == 422
    assert upcoming_response.status_code == 422
    assert complete_response.status_code == 422
    assert due_response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_review_routes_reject_out_of_scope_course_ids() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(12),
    )
    login(harness)

    due_response = harness.client.get("/api/review/due?learning_path_id=99")
    upcoming_response = harness.client.get("/api/review/upcoming?learning_path_id=99")
    schedules_response = harness.client.get("/api/review/schedules?learning_path_id=99")
    schedule_response = harness.client.post(
        "/api/review/schedules",
        json={"learning_path_id": 99, "topic": "Graphs"},
        headers=csrf_headers(harness),
    )
    complete_response = harness.client.post(
        "/api/review/complete",
        json={"learning_path_id": 99, "topic": "Graphs", "score": 0.75},
        headers=csrf_headers(harness),
    )

    assert due_response.status_code == 403
    assert upcoming_response.status_code == 403
    assert schedules_response.status_code == 403
    assert schedule_response.status_code == 403
    assert complete_response.status_code == 403


def test_review_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/review/due"]["get"]["tags"] == ["review"]
    assert openapi["paths"]["/api/review/due"]["get"]["operationId"] == "listDueReviews"
    assert openapi["paths"]["/api/review/upcoming"]["get"]["operationId"] == "listUpcomingReviews"
    assert openapi["paths"]["/api/review/schedules"]["get"]["operationId"] == "listReviewSchedules"
    assert openapi["paths"]["/api/review/schedules"]["post"]["operationId"] == "scheduleReview"
    assert openapi["paths"]["/api/review/complete"]["post"]["operationId"] == "completeReview"
