"""Content search API route tests."""

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


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        course_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


def test_search_content_requires_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    response = harness.client.post(
        "/api/search",
        json={"content_source_id": 12, "query": "dynamic programming"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "auth.failed", "params": {}}}


def test_search_content_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
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
        "/api/search",
        json={
            "content_source_id": 12,
            "query": "dynamic programming",
            "n_results": 3,
            "source_filter": "transcript",
            "learning_path_id": 12,
            "missed_only": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "content_item_id": "episode-1",
                "title": "Lecture 1",
                "chunk_text": "Optimal substructure and overlapping subproblems.",
                "start_time": 12.5,
                "end_time": 24.0,
                "score": 0.89,
                "source": "transcript",
            },
        ],
    }


def test_search_content_uses_session_scope_when_learning_path_id_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
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
        "/api/search",
        json={"content_source_id": 12, "query": "dynamic programming"},
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}
    assert calls == [(12, 12)]


def test_search_content_rejects_out_of_scope_learning_path_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
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
        "/api/search",
        json={"content_source_id": 12, "query": "dynamic programming", "learning_path_id": 99},
    )

    assert response.status_code == 403
    assert calls == []


def test_search_content_rejects_cross_scope_content_source_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
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
        "/api/search",
        json={"content_source_id": 99, "query": "dynamic programming"},
    )

    assert response.status_code == 403
    assert calls == []


def test_search_content_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/search",
        json={"content_source_id": 0, "query": ""},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_search_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    operation = harness.app.openapi()["paths"]["/api/search"]["post"]

    assert operation["tags"] == ["search"]
    assert operation["operationId"] == "searchContent"
    assert "requestBody" in operation


def test_search_content_maps_document_filter_to_index_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
    )
    login(harness)

    async def fake_search_lectures(
        _app: AppContainer,
        _module_id: int,
        _query: str,
        *,
        n_results: int = 5,
        source_filter: str | None = None,
        course_id: int | None = None,
        missed_only: bool = False,
    ) -> list[LectureSearchResult]:
        assert source_filter == "pdf"
        return [
            LectureSearchResult(
                episode_id="mat-7",
                title="Skriptum",
                chunk_text="Amortized analysis.",
                start_time=0.0,
                end_time=0.0,
                score=0.42,
                source="pdf",
            ),
        ]

    monkeypatch.setattr(search_router, "search_lectures", fake_search_lectures)

    response = harness.client.post(
        "/api/search",
        json={
            "content_source_id": 12,
            "query": "amortized analysis",
            "source_filter": "document",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["source"] == "document"


def test_search_content_rejects_unknown_source_filter() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(12),
    )
    login(harness)

    response = harness.client.post(
        "/api/search",
        json={"content_source_id": 12, "query": "greedy", "source_filter": "lecture"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}
