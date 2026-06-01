"""Lecture search API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.api.routers import search as search_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import LectureSearchResult

from ._session_helpers import build_harness, login

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


def test_search_lectures_requires_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    response = harness.client.post(
        "/api/search/lectures",
        json={"module_id": 12, "query": "dynamic programming"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "auth.failed", "params": {}}}


def test_search_lectures_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(),
    )
    login(harness)

    async def fake_search_lectures(
        app: AppContainer,
        module_id: int,
        query: str,
        *,
        n_results: int = 5,
        source_filter: str | None = None,
        course_id: int | None = None,
        missed_only: bool = False,
    ) -> list[LectureSearchResult]:
        assert app is fake_app
        assert module_id == 12
        assert query == "dynamic programming"
        assert n_results == 3
        assert source_filter == "lecture"
        assert course_id == 12
        assert missed_only is True
        return [
            LectureSearchResult(
                episode_id="episode-1",
                title="Lecture 1",
                chunk_text="Optimal substructure and overlapping subproblems.",
                start_time=12.5,
                end_time=24.0,
                score=0.89,
                source="lecture",
            ),
        ]

    monkeypatch.setattr(search_router, "search_lectures", fake_search_lectures)

    response = harness.client.post(
        "/api/search/lectures",
        json={
            "module_id": 12,
            "query": "dynamic programming",
            "n_results": 3,
            "source_filter": "lecture",
            "course_id": 12,
            "missed_only": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "episode_id": "episode-1",
                "title": "Lecture 1",
                "chunk_text": "Optimal substructure and overlapping subproblems.",
                "start_time": 12.5,
                "end_time": 24.0,
                "score": 0.89,
                "source": "lecture",
            },
        ],
    }


def test_search_lectures_uses_session_course_when_course_id_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[tuple[int, int | None]] = []

    async def fake_search_lectures(
        _app: AppContainer,
        module_id: int,
        _query: str,
        *,
        n_results: int = 5,
        source_filter: str | None = None,
        course_id: int | None = None,
        missed_only: bool = False,
    ) -> list[LectureSearchResult]:
        assert n_results == 5
        assert source_filter is None
        assert missed_only is False
        calls.append((module_id, course_id))
        return []

    monkeypatch.setattr(search_router, "search_lectures", fake_search_lectures)

    response = harness.client.post(
        "/api/search/lectures",
        json={"module_id": 12, "query": "dynamic programming"},
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}
    assert calls == [(12, 12)]


def test_search_lectures_rejects_out_of_scope_course_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_search_lectures(
        _app: AppContainer,
        module_id: int,
        _query: str,
        *,
        n_results: int = 5,
        source_filter: str | None = None,
        course_id: int | None = None,
        missed_only: bool = False,
    ) -> list[LectureSearchResult]:
        calls.append(f"{module_id}:{course_id}:{n_results}:{source_filter}:{missed_only}")
        return []

    monkeypatch.setattr(search_router, "search_lectures", fake_search_lectures)

    response = harness.client.post(
        "/api/search/lectures",
        json={"module_id": 12, "query": "dynamic programming", "course_id": 99},
    )

    assert response.status_code == 403
    assert calls == []


def test_search_lectures_rejects_cross_course_module_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=course_tenant(12),
    )
    login(harness)
    calls: list[int] = []

    async def fake_search_lectures(
        _app: AppContainer,
        module_id: int,
        _query: str,
        *,
        n_results: int = 5,
        source_filter: str | None = None,
        course_id: int | None = None,
        missed_only: bool = False,
    ) -> list[LectureSearchResult]:
        calls.append(module_id)
        return []

    monkeypatch.setattr(search_router, "search_lectures", fake_search_lectures)

    response = harness.client.post(
        "/api/search/lectures",
        json={"module_id": 99, "query": "dynamic programming"},
    )

    assert response.status_code == 403
    assert calls == []


def test_search_lectures_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/search/lectures",
        json={"module_id": 0, "query": ""},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_search_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    operation = harness.app.openapi()["paths"]["/api/search/lectures"]["post"]

    assert operation["tags"] == ["search"]
    assert operation["operationId"] == "searchLectureContent"
    assert "requestBody" in operation
