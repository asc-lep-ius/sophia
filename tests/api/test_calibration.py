"""Calibration API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.api.routers import calibration as calibration_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import ConfidenceRating

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


def course_tenant(course_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        course_id=str(course_id),
        cohort_id="cohort-a",
        role="student",
    )


def test_calibration_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    ratings_response = harness.client.get("/api/calibration/ratings?course_id=12")
    blind_spots_response = harness.client.get("/api/calibration/blind-spots?course_id=12")
    rate_response = harness.client.post(
        "/api/calibration/ratings",
        json={"course_id": 12, "topic": "Graphs", "rating": 4},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    actual_response = harness.client.patch(
        "/api/calibration/actual-score",
        json={"course_id": 12, "topic": "Graphs", "actual": 0.5},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert ratings_response.status_code == 401
    assert blind_spots_response.status_code == 401
    assert rate_response.status_code == 401
    assert actual_response.status_code == 401


def test_calibration_read_routes_return_response_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)
    rating = ConfidenceRating(
        topic="Graphs",
        course_id=12,
        predicted=0.75,
        actual=0.5,
        rated_at="2026-05-26T12:00:00Z",
    )

    async def fake_get_confidence_ratings(db: object, course_id: int) -> list[ConfidenceRating]:
        assert db is fake_app.db
        assert course_id == 12
        return [rating]

    async def fake_get_blind_spots(db: object, course_id: int) -> list[ConfidenceRating]:
        assert db is fake_app.db
        assert course_id == 12
        return [rating]

    monkeypatch.setattr(calibration_router, "get_confidence_ratings", fake_get_confidence_ratings)
    monkeypatch.setattr(calibration_router, "get_blind_spots", fake_get_blind_spots)

    ratings_response = harness.client.get("/api/calibration/ratings?course_id=12")
    blind_spots_response = harness.client.get("/api/calibration/blind-spots?course_id=12")

    expected_rating = {
        "topic": "Graphs",
        "course_id": 12,
        "predicted": 0.75,
        "actual": 0.5,
        "rated_at": "2026-05-26T12:00:00Z",
        "calibration_error": 0.25,
        "is_blind_spot": True,
        "difficulty_level": "transfer",
    }
    assert ratings_response.status_code == 200
    assert ratings_response.json() == {"course_id": 12, "ratings": [expected_rating]}
    assert blind_spots_response.status_code == 200
    assert blind_spots_response.json() == {"course_id": 12, "ratings": [expected_rating]}


def test_calibration_ratings_return_404_for_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_get_confidence_ratings(_db: object, _course_id: int) -> list[ConfidenceRating]:
        return []

    monkeypatch.setattr(calibration_router, "get_confidence_ratings", fake_get_confidence_ratings)

    response = harness.client.get("/api/calibration/ratings?course_id=12&topic=Missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_rate_confidence_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/calibration/ratings",
        json={"course_id": 12, "topic": "Graphs", "rating": 4},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_rate_confidence_returns_saved_rating(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_rate_confidence(
        app: AppContainer,
        topic: str,
        course_id: int,
        rating: int,
    ) -> ConfidenceRating:
        assert app is fake_app
        assert topic == "Graphs"
        assert course_id == 12
        assert rating == 4
        return ConfidenceRating(
            topic="Graphs",
            course_id=12,
            predicted=0.75,
            actual=None,
            rated_at="2026-05-26T13:00:00Z",
        )

    monkeypatch.setattr(calibration_router, "rate_confidence", fake_rate_confidence)

    response = harness.client.post(
        "/api/calibration/ratings",
        json={"course_id": 12, "topic": "Graphs", "rating": 4},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "rating": {
            "topic": "Graphs",
            "course_id": 12,
            "predicted": 0.75,
            "actual": None,
            "rated_at": "2026-05-26T13:00:00Z",
            "calibration_error": None,
            "is_blind_spot": False,
            "difficulty_level": "transfer",
        },
    }


def test_update_actual_score_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.patch(
        "/api/calibration/actual-score",
        json={"course_id": 12, "topic": "Graphs", "actual": 0.5},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_update_actual_score_returns_update_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)
    calls: list[tuple[object, str, int, float]] = []

    async def fake_update_actual_score(
        db: object,
        topic: str,
        course_id: int,
        actual: float,
    ) -> None:
        calls.append((db, topic, course_id, actual))

    monkeypatch.setattr(calibration_router, "update_actual_score", fake_update_actual_score)

    response = harness.client.patch(
        "/api/calibration/actual-score",
        json={"course_id": 12, "topic": "Graphs", "actual": 0.5},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {"course_id": 12, "topic": "Graphs", "actual": 0.5, "updated": True}
    assert calls == [(fake_app.db, "Graphs", 12, 0.5)]


def test_calibration_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    ratings_response = harness.client.get("/api/calibration/ratings?course_id=0")
    rate_response = harness.client.post(
        "/api/calibration/ratings",
        json={"course_id": 12, "topic": "Graphs", "rating": 0},
        headers=csrf_headers(harness),
    )
    actual_response = harness.client.patch(
        "/api/calibration/actual-score",
        json={"course_id": 12, "topic": "Graphs", "actual": 1.5},
        headers=csrf_headers(harness),
    )

    assert ratings_response.status_code == 422
    assert rate_response.status_code == 422
    assert actual_response.status_code == 422
    assert ratings_response.json() == {
        "detail": {"code": "request.validation_failed", "params": {}}
    }


def test_calibration_routes_reject_out_of_scope_course_ids() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=course_tenant(12),
    )
    login(harness)

    ratings_response = harness.client.get("/api/calibration/ratings?course_id=99")
    blind_spots_response = harness.client.get("/api/calibration/blind-spots?course_id=99")
    rate_response = harness.client.post(
        "/api/calibration/ratings",
        json={"course_id": 99, "topic": "Graphs", "rating": 4},
        headers=csrf_headers(harness),
    )
    actual_response = harness.client.patch(
        "/api/calibration/actual-score",
        json={"course_id": 99, "topic": "Graphs", "actual": 0.5},
        headers=csrf_headers(harness),
    )

    assert ratings_response.status_code == 403
    assert blind_spots_response.status_code == 403
    assert rate_response.status_code == 403
    assert actual_response.status_code == 403


def test_calibration_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/calibration/ratings"]["get"]["tags"] == ["calibration"]
    assert (
        openapi["paths"]["/api/calibration/ratings"]["get"]["operationId"]
        == "listCalibrationRatings"
    )
    assert (
        openapi["paths"]["/api/calibration/blind-spots"]["get"]["operationId"]
        == "listCalibrationBlindSpots"
    )
    assert (
        openapi["paths"]["/api/calibration/ratings"]["post"]["operationId"]
        == "saveCalibrationConfidenceRating"
    )
    assert (
        openapi["paths"]["/api/calibration/actual-score"]["patch"]["operationId"]
        == "updateCalibrationActualScore"
    )
