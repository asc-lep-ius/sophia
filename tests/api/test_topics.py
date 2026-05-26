"""Topics API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.api.routers import topics as topics_router
from sophia.domain.models import ConfidenceRating, TopicMapping, TopicSource

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


def test_topic_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    topics_response = harness.client.get("/api/topics?course_id=12")
    extract_response = harness.client.post(
        "/api/topics/extract",
        json={"module_id": 12},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    confidence_response = harness.client.get("/api/topics/confidence?course_id=12")

    assert topics_response.status_code == 401
    assert extract_response.status_code == 401
    assert confidence_response.status_code == 401


def test_list_topics_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_get_course_topics(app: AppContainer, course_id: int) -> list[TopicMapping]:
        assert app is fake_app
        assert course_id == 12
        return [
            TopicMapping(
                topic="Dynamic programming",
                course_id=12,
                source=TopicSource.LECTURE,
                frequency=3,
            ),
        ]

    monkeypatch.setattr(topics_router, "get_course_topics", fake_get_course_topics)

    response = harness.client.get("/api/topics?course_id=12")

    assert response.status_code == 200
    assert response.json() == {
        "course_id": 12,
        "topics": [
            {
                "topic": "Dynamic programming",
                "course_id": 12,
                "source": "lecture",
                "frequency": 3,
            },
        ],
    }


def test_extract_topics_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post("/api/topics/extract", json={"module_id": 12})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_extract_topics_returns_extracted_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_extract_topics_from_lectures(
        app: AppContainer,
        module_id: int,
        *,
        force: bool = False,
    ) -> list[TopicMapping]:
        assert app is fake_app
        assert module_id == 12
        assert force is True
        return [TopicMapping(topic="Graphs", course_id=12, source=TopicSource.LECTURE)]

    monkeypatch.setattr(
        topics_router,
        "extract_topics_from_lectures",
        fake_extract_topics_from_lectures,
    )

    response = harness.client.post(
        "/api/topics/extract",
        json={"module_id": 12, "force": True},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "module_id": 12,
        "topics": [
            {"topic": "Graphs", "course_id": 12, "source": "lecture", "frequency": 1},
        ],
    }


def test_save_manual_topic_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/topics/manual",
        json={"course_id": 12, "topic": "Amortized analysis"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_save_manual_topic_returns_saved_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_save_manual_topic(
        app: AppContainer,
        topic: str,
        course_id: int,
    ) -> TopicMapping | None:
        assert app is fake_app
        assert topic == "Amortized analysis"
        assert course_id == 12
        return TopicMapping(topic=topic, course_id=course_id, source=TopicSource.MANUAL)

    monkeypatch.setattr(topics_router, "save_manual_topic", fake_save_manual_topic)

    response = harness.client.post(
        "/api/topics/manual",
        json={"course_id": 12, "topic": "Amortized analysis"},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "topic": {
            "topic": "Amortized analysis",
            "course_id": 12,
            "source": "manual",
            "frequency": 1,
        },
    }


def test_confidence_routes_return_response_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_get_confidence_ratings(
        db: object,
        course_id: int,
    ) -> list[ConfidenceRating]:
        assert db is fake_app.db
        assert course_id == 12
        return [
            ConfidenceRating(
                topic="Graphs",
                course_id=12,
                predicted=0.75,
                actual=None,
                rated_at="2026-05-26T12:00:00Z",
            ),
        ]

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
            rated_at="2026-05-26T12:00:00Z",
        )

    monkeypatch.setattr(topics_router, "get_confidence_ratings", fake_get_confidence_ratings)
    monkeypatch.setattr(topics_router, "rate_confidence", fake_rate_confidence)

    list_response = harness.client.get("/api/topics/confidence?course_id=12")
    save_response = harness.client.post(
        "/api/topics/confidence",
        json={"course_id": 12, "topic": "Graphs", "rating": 4},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 200
    assert list_response.json() == {
        "course_id": 12,
        "ratings": [
            {
                "topic": "Graphs",
                "course_id": 12,
                "predicted": 0.75,
                "actual": None,
                "rated_at": "2026-05-26T12:00:00Z",
                "calibration_error": None,
                "is_blind_spot": False,
            },
        ],
    }
    assert save_response.status_code == 200
    assert save_response.json() == {
        "rating": {
            "topic": "Graphs",
            "course_id": 12,
            "predicted": 0.75,
            "actual": None,
            "rated_at": "2026-05-26T12:00:00Z",
            "calibration_error": None,
            "is_blind_spot": False,
        },
    }


def test_topic_confidence_lookup_returns_404_for_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    async def fake_get_confidence_ratings(
        _db: object,
        _course_id: int,
    ) -> list[ConfidenceRating]:
        return []

    monkeypatch.setattr(topics_router, "get_confidence_ratings", fake_get_confidence_ratings)

    response = harness.client.get("/api/topics/confidence?course_id=12&topic=Missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_topic_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    list_response = harness.client.get("/api/topics?course_id=0")
    extract_response = harness.client.post(
        "/api/topics/extract",
        json={"module_id": 0},
        headers=csrf_headers(harness),
    )
    confidence_response = harness.client.post(
        "/api/topics/confidence",
        json={"course_id": 12, "topic": "Graphs", "rating": 6},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 422
    assert extract_response.status_code == 422
    assert confidence_response.status_code == 422
    assert list_response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_topics_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/topics"]["get"]["tags"] == ["topics"]
    assert openapi["paths"]["/api/topics"]["get"]["operationId"] == "listTopics"
    assert openapi["paths"]["/api/topics/extract"]["post"]["operationId"] == "extractTopics"
    assert openapi["paths"]["/api/topics/manual"]["post"]["operationId"] == "saveManualTopic"
    assert (
        openapi["paths"]["/api/topics/confidence"]["get"]["operationId"]
        == "listTopicConfidenceRatings"
    )
    assert (
        openapi["paths"]["/api/topics/confidence"]["post"]["operationId"]
        == "saveTopicConfidenceRating"
    )
