"""Quickstart API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sophia.api.routers import quickstart as quickstart_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import Course, Deadline, DeadlineType, TopicMapping, TopicSource
from sophia.services.quickstart import QuickstartOverview

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        course_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


def sample_course(course_id: int = 12) -> Course:
    return Course(
        id=course_id,
        fullname="Algorithms",
        shortname="186.813",
        url="https://tu.test/course/12",
    )


def sample_deadline() -> Deadline:
    return Deadline(
        id="assign:1",
        name="Homework 1",
        course_id=12,
        course_name="Algorithms",
        deadline_type=DeadlineType.ASSIGNMENT,
        due_at=datetime(2026, 6, 1, 10, tzinfo=UTC),
    )


def test_quickstart_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    overview_response = harness.client.get("/api/quickstart/overview?learning_path_id=12")
    confidence_response = harness.client.post(
        "/api/quickstart/confidence",
        json={"learning_path_id": 12, "ratings": {"Graphs": 4}},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    topics_response = harness.client.post(
        "/api/quickstart/manual-topics",
        json={"learning_path_id": 12, "topics": ["Graphs"]},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    count_response = harness.client.get("/api/quickstart/session-count?learning_path_id=12")

    assert overview_response.status_code == 401
    assert confidence_response.status_code == 401
    assert topics_response.status_code == 401
    assert count_response.status_code == 401


def test_quickstart_routes_return_response_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    saved_confidence: list[tuple[int, dict[str, int]]] = []

    async def fake_get_quickstart_overview(
        app: AppContainer,
        *,
        course_id: int | None = None,
    ) -> QuickstartOverview:
        assert app is fake_app
        assert course_id == 12
        return QuickstartOverview(
            courses=[sample_course()],
            topics=[TopicMapping(topic="Graphs", course_id=12, source=TopicSource.LECTURE)],
            nearest_deadline=sample_deadline(),
            completed_session_count=2,
        )

    async def fake_save_initial_confidence(
        app: AppContainer,
        *,
        course_id: int,
        ratings: dict[str, int],
    ) -> int:
        assert app is fake_app
        saved_confidence.append((course_id, ratings))
        return len(ratings)

    async def fake_save_manual_topics(
        app: AppContainer,
        *,
        course_id: int,
        topics: list[str],
    ) -> list[TopicMapping]:
        assert app is fake_app
        assert topics == ["Graphs", "Flows"]
        return [
            TopicMapping(topic="Graphs", course_id=course_id, source=TopicSource.MANUAL),
            TopicMapping(topic="Flows", course_id=course_id, source=TopicSource.MANUAL),
        ]

    async def fake_get_completed_session_count(
        app: AppContainer,
        *,
        course_id: int | None = None,
    ) -> int:
        assert app is fake_app
        assert course_id == 12
        return 2

    monkeypatch.setattr(
        quickstart_router,
        "get_quickstart_overview",
        fake_get_quickstart_overview,
    )
    monkeypatch.setattr(
        quickstart_router,
        "save_initial_confidence",
        fake_save_initial_confidence,
    )
    monkeypatch.setattr(quickstart_router, "save_manual_topics", fake_save_manual_topics)
    monkeypatch.setattr(
        quickstart_router,
        "get_completed_session_count",
        fake_get_completed_session_count,
    )

    overview_response = harness.client.get("/api/quickstart/overview?learning_path_id=12")
    confidence_response = harness.client.post(
        "/api/quickstart/confidence",
        json={"learning_path_id": 12, "ratings": {"Graphs": 4, "Flows": 3}},
        headers=csrf_headers(harness),
    )
    topics_response = harness.client.post(
        "/api/quickstart/manual-topics",
        json={"learning_path_id": 12, "topics": ["Graphs", "Flows"]},
        headers=csrf_headers(harness),
    )
    count_response = harness.client.get("/api/quickstart/session-count?learning_path_id=12")

    assert overview_response.status_code == 200
    assert overview_response.json() == {
        "learning_path_id": 12,
        "learning_paths": [
            {
                "id": 12,
                "title": "Algorithms",
                "short_title": "186.813",
                "url": "https://tu.test/course/12",
            },
        ],
        "topics": [
            {"topic": "Graphs", "learning_path_id": 12, "source": "transcript", "frequency": 1},
        ],
        "nearest_deadline": {
            "id": "assign:1",
            "name": "Homework 1",
            "learning_path_id": 12,
            "learning_path_name": "Algorithms",
            "deadline_type": "assignment",
            "due_at": "2026-06-01T10:00:00Z",
            "grade_weight": None,
            "submission_status": None,
            "url": None,
            "extra": {},
        },
        "completed_session_count": 2,
    }
    assert confidence_response.json() == {"learning_path_id": 12, "saved_count": 2}
    assert topics_response.json() == {
        "learning_path_id": 12,
        "topics": [
            {"topic": "Graphs", "learning_path_id": 12, "source": "manual", "frequency": 1},
            {"topic": "Flows", "learning_path_id": 12, "source": "manual", "frequency": 1},
        ],
    }
    assert count_response.json() == {"learning_path_id": 12, "completed_session_count": 2}
    assert saved_confidence == [(12, {"Graphs": 4, "Flows": 3})]


def test_quickstart_optional_routes_use_session_learning_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    course_ids: list[int | None] = []

    async def fake_get_quickstart_overview(
        app: AppContainer,
        *,
        course_id: int | None = None,
    ) -> QuickstartOverview:
        assert app is fake_app
        course_ids.append(course_id)
        if course_id is None:
            return QuickstartOverview(
                courses=[sample_course(99)],
                topics=[TopicMapping(topic="Databases", course_id=99, source=TopicSource.MANUAL)],
                nearest_deadline=None,
                completed_session_count=99,
            )
        return QuickstartOverview(
            courses=[sample_course(course_id)],
            topics=[TopicMapping(topic="Graphs", course_id=course_id, source=TopicSource.MANUAL)],
            nearest_deadline=sample_deadline(),
            completed_session_count=2,
        )

    async def fake_get_completed_session_count(
        app: AppContainer,
        *,
        course_id: int | None = None,
    ) -> int:
        assert app is fake_app
        course_ids.append(course_id)
        return 99 if course_id is None else 2

    monkeypatch.setattr(
        quickstart_router,
        "get_quickstart_overview",
        fake_get_quickstart_overview,
    )
    monkeypatch.setattr(
        quickstart_router,
        "get_completed_session_count",
        fake_get_completed_session_count,
    )

    overview_response = harness.client.get("/api/quickstart/overview")
    count_response = harness.client.get("/api/quickstart/session-count")

    assert overview_response.status_code == 200
    assert count_response.status_code == 200
    assert overview_response.json()["learning_path_id"] == 12
    assert overview_response.json()["learning_paths"] == [
        {
            "id": 12,
            "title": "Algorithms",
            "short_title": "186.813",
            "url": "https://tu.test/course/12",
        },
    ]
    assert overview_response.json()["completed_session_count"] == 2
    assert count_response.json() == {"learning_path_id": 12, "completed_session_count": 2}
    assert course_ids == [12, 12]


def test_quickstart_overview_missing_filtered_course_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_quickstart_overview(
        _app: AppContainer,
        *,
        course_id: int | None = None,
    ) -> QuickstartOverview:
        return QuickstartOverview(
            courses=[],
            topics=[],
            nearest_deadline=None,
            completed_session_count=0,
        )

    monkeypatch.setattr(
        quickstart_router,
        "get_quickstart_overview",
        fake_get_quickstart_overview,
    )

    response = harness.client.get("/api/quickstart/overview?learning_path_id=12")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_quickstart_mutating_routes_require_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    confidence_response = harness.client.post(
        "/api/quickstart/confidence",
        json={"learning_path_id": 12, "ratings": {"Graphs": 4}},
    )
    topics_response = harness.client.post(
        "/api/quickstart/manual-topics",
        json={"learning_path_id": 12, "topics": ["Graphs"]},
    )

    assert confidence_response.status_code == 403
    assert topics_response.status_code == 403


def test_quickstart_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    overview_response = harness.client.get("/api/quickstart/overview?learning_path_id=0")
    confidence_response = harness.client.post(
        "/api/quickstart/confidence",
        json={"learning_path_id": 12, "ratings": {"Graphs": 0}},
        headers=csrf_headers(harness),
    )
    topics_response = harness.client.post(
        "/api/quickstart/manual-topics",
        json={"learning_path_id": 12, "topics": []},
        headers=csrf_headers(harness),
    )

    assert overview_response.status_code == 422
    assert confidence_response.status_code == 422
    assert topics_response.status_code == 422
    assert overview_response.json() == {
        "detail": {"code": "request.validation_failed", "params": {}}
    }


def test_quickstart_routes_reject_out_of_scope_learning_path_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_quickstart_overview(
        _app: AppContainer,
        *,
        course_id: int | None = None,
    ) -> QuickstartOverview:
        calls.append(f"overview:{course_id}")
        return QuickstartOverview(
            courses=[],
            topics=[],
            nearest_deadline=None,
            completed_session_count=0,
        )

    monkeypatch.setattr(
        quickstart_router,
        "get_quickstart_overview",
        fake_get_quickstart_overview,
    )

    overview_response = harness.client.get("/api/quickstart/overview?learning_path_id=99")
    confidence_response = harness.client.post(
        "/api/quickstart/confidence",
        json={"learning_path_id": 99, "ratings": {"Graphs": 4}},
        headers=csrf_headers(harness),
    )
    topics_response = harness.client.post(
        "/api/quickstart/manual-topics",
        json={"learning_path_id": 99, "topics": ["Graphs"]},
        headers=csrf_headers(harness),
    )
    count_response = harness.client.get("/api/quickstart/session-count?learning_path_id=99")

    assert overview_response.status_code == 403
    assert confidence_response.status_code == 403
    assert topics_response.status_code == 403
    assert count_response.status_code == 403
    assert calls == []


def test_quickstart_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/quickstart/overview"]["get"]["tags"] == ["quickstart"]
    assert openapi["paths"]["/api/quickstart/overview"]["get"]["operationId"] == (
        "getQuickstartOverview"
    )
    assert openapi["paths"]["/api/quickstart/confidence"]["post"]["operationId"] == (
        "saveQuickstartConfidence"
    )
    assert openapi["paths"]["/api/quickstart/manual-topics"]["post"]["operationId"] == (
        "saveQuickstartManualTopics"
    )
    assert openapi["paths"]["/api/quickstart/session-count"]["get"]["operationId"] == (
        "getQuickstartSessionCount"
    )
