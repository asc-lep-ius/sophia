"""Study API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.api.routers import study as study_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import FlashcardSource, StudentFlashcard, StudySession

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


class FakeStudySessionCursor:
    def __init__(self, row: tuple[int] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[int] | None:
        return self._row


class FakeStudySessionDb:
    def __init__(self, session_courses: dict[int, int]) -> None:
        self._session_courses = session_courses

    async def execute(self, _query: str, parameters: tuple[int]) -> FakeStudySessionCursor:
        course_id = self._session_courses.get(parameters[0])
        return FakeStudySessionCursor(None if course_id is None else (course_id,))


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        course_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


def test_study_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    list_response = harness.client.get("/api/study/sessions?learning_path_id=12")
    start_response = harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": 12, "topic": "Graphs"},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    complete_response = harness.client.post(
        "/api/study/sessions/99/complete",
        json={"pre_test_score": 0.25, "post_test_score": 0.75},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    flashcard_response = harness.client.post(
        "/api/study/flashcards",
        json={"learning_path_id": 12, "topic": "Graphs", "front": "Q", "back": "A"},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert list_response.status_code == 401
    assert start_response.status_code == 401
    assert complete_response.status_code == 401
    assert flashcard_response.status_code == 401


def test_list_study_sessions_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_study_sessions(
        db: object,
        course_id: int,
        topic: str | None = None,
    ) -> list[StudySession]:
        assert db is fake_app.db
        assert course_id == 12
        assert topic == "Graphs"
        return [
            StudySession(
                id=7,
                course_id=12,
                topic="Graphs",
                pre_test_score=0.25,
                post_test_score=0.75,
                started_at="2026-05-26T12:00:00Z",
                completed_at="2026-05-26T12:30:00Z",
            ),
        ]

    monkeypatch.setattr(study_router, "get_study_sessions", fake_get_study_sessions)

    response = harness.client.get("/api/study/sessions?learning_path_id=12&topic=Graphs")

    assert response.status_code == 200
    assert response.json() == {
        "learning_path_id": 12,
        "sessions": [
            {
                "id": 7,
                "learning_path_id": 12,
                "topic": "Graphs",
                "pre_test_score": 0.25,
                "post_test_score": 0.75,
                "started_at": "2026-05-26T12:00:00Z",
                "completed_at": "2026-05-26T12:30:00Z",
                "improvement": 0.5,
            },
        ],
    }


def test_list_study_sessions_returns_404_for_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_study_sessions(
        _db: object,
        _course_id: int,
        _topic: str | None = None,
    ) -> list[StudySession]:
        return []

    monkeypatch.setattr(study_router, "get_study_sessions", fake_get_study_sessions)

    response = harness.client.get("/api/study/sessions?learning_path_id=12&topic=Missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_start_study_session_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": 12, "topic": "Graphs"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_start_study_session_returns_created_session(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_start_study_session(
        db: object,
        course_id: int,
        topic: str,
    ) -> StudySession:
        assert db is fake_app.db
        assert course_id == 12
        assert topic == "Graphs"
        return StudySession(
            id=8,
            course_id=12,
            topic="Graphs",
            started_at="2026-05-26T13:00:00Z",
        )

    monkeypatch.setattr(study_router, "start_study_session", fake_start_study_session)

    response = harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": 12, "topic": "Graphs"},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "session": {
            "id": 8,
            "learning_path_id": 12,
            "topic": "Graphs",
            "pre_test_score": None,
            "post_test_score": None,
            "started_at": "2026-05-26T13:00:00Z",
            "completed_at": None,
            "improvement": None,
        },
    }


def test_complete_study_session_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/study/sessions/8/complete",
        json={"pre_test_score": 0.25, "post_test_score": 0.75},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_complete_study_session_returns_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=FakeStudySessionDb({8: 12}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    calls: list[tuple[object, int, float, float]] = []

    async def fake_complete_study_session(
        db: object,
        session_id: int,
        pre_test_score: float,
        post_test_score: float,
    ) -> None:
        calls.append((db, session_id, pre_test_score, post_test_score))

    monkeypatch.setattr(study_router, "complete_study_session", fake_complete_study_session)

    response = harness.client.post(
        "/api/study/sessions/8/complete",
        json={"pre_test_score": 0.25, "post_test_score": 0.75},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {"session_id": 8, "completed": True}
    assert calls == [(fake_app.db, 8, 0.25, 0.75)]


def test_save_flashcard_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/study/flashcards",
        json={"learning_path_id": 12, "topic": "Graphs", "front": "Q", "back": "A"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_save_flashcard_returns_saved_flashcard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_save_flashcard(
        db: object,
        course_id: int,
        topic: str,
        front: str,
        back: str,
        source: str = "study",
    ) -> StudentFlashcard:
        assert db is fake_app.db
        assert course_id == 12
        assert topic == "Graphs"
        assert front == "What is a cut?"
        assert back == "A partition of graph vertices."
        assert source == "manual"
        return StudentFlashcard(
            id=9,
            course_id=12,
            topic="Graphs",
            front=front,
            back=back,
            source=FlashcardSource.MANUAL,
            created_at="2026-05-26T14:00:00Z",
        )

    monkeypatch.setattr(study_router, "save_flashcard", fake_save_flashcard)

    response = harness.client.post(
        "/api/study/flashcards",
        json={
            "learning_path_id": 12,
            "topic": "Graphs",
            "front": "What is a cut?",
            "back": "A partition of graph vertices.",
            "source": "manual",
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "flashcard": {
            "id": 9,
            "learning_path_id": 12,
            "topic": "Graphs",
            "front": "What is a cut?",
            "back": "A partition of graph vertices.",
            "source": "manual",
            "created_at": "2026-05-26T14:00:00Z",
        },
    }


def test_study_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    list_response = harness.client.get("/api/study/sessions?learning_path_id=0")
    start_response = harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": 12, "topic": ""},
        headers=csrf_headers(harness),
    )
    complete_response = harness.client.post(
        "/api/study/sessions/0/complete",
        json={"pre_test_score": 1.5, "post_test_score": 0.75},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 422
    assert start_response.status_code == 422
    assert complete_response.status_code == 422
    assert list_response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_study_routes_reject_out_of_scope_course_ids() -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(12),
    )
    login(harness)

    list_response = harness.client.get("/api/study/sessions?learning_path_id=99")
    start_response = harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": 99, "topic": "Graphs"},
        headers=csrf_headers(harness),
    )
    flashcard_response = harness.client.post(
        "/api/study/flashcards",
        json={"learning_path_id": 99, "topic": "Graphs", "front": "Q", "back": "A"},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 403
    assert start_response.status_code == 403
    assert flashcard_response.status_code == 403


def test_complete_study_session_rejects_cross_course_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=FakeStudySessionDb({8: 99}))
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
    )
    login(harness)
    calls: list[int] = []

    async def fake_complete_study_session(
        _db: object,
        session_id: int,
        _pre_test_score: float,
        _post_test_score: float,
    ) -> None:
        calls.append(session_id)

    monkeypatch.setattr(study_router, "complete_study_session", fake_complete_study_session)

    response = harness.client.post(
        "/api/study/sessions/8/complete",
        json={"pre_test_score": 0.25, "post_test_score": 0.75},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 403
    assert calls == []


def test_invalid_flashcard_source_returns_422_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    calls: list[str] = []

    async def fake_save_flashcard(
        _db: object,
        _course_id: int,
        _topic: str,
        _front: str,
        _back: str,
        source: str = "study",
    ) -> StudentFlashcard:
        calls.append(source)
        return StudentFlashcard(
            id=9,
            course_id=12,
            topic="Graphs",
            front="Q",
            back="A",
            source=FlashcardSource.STUDY,
            created_at="2026-05-26T14:00:00Z",
        )

    monkeypatch.setattr(study_router, "save_flashcard", fake_save_flashcard)

    response = harness.client.post(
        "/api/study/flashcards",
        json={
            "learning_path_id": 12,
            "topic": "Graphs",
            "front": "Q",
            "back": "A",
            "source": "imported",
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 422
    assert calls == []


def test_study_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/study/sessions"]["get"]["tags"] == ["study"]
    assert openapi["paths"]["/api/study/sessions"]["get"]["operationId"] == "listStudySessions"
    assert openapi["paths"]["/api/study/sessions"]["post"]["operationId"] == "startStudySession"
    assert (
        openapi["paths"]["/api/study/sessions/{session_id}/complete"]["post"]["operationId"]
        == "completeStudySession"
    )
    assert openapi["paths"]["/api/study/flashcards"]["post"]["operationId"] == "saveStudyFlashcard"


def test_flashcard_transcript_source_maps_to_domain_lecture_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
    )
    login(harness)

    async def fake_save_flashcard(
        _db: object,
        course_id: int,
        topic: str,
        front: str,
        back: str,
        source: str = "study",
    ) -> StudentFlashcard:
        assert source == "lecture"
        return StudentFlashcard(
            id=7,
            course_id=course_id,
            topic=topic,
            front=front,
            back=back,
            source=FlashcardSource.LECTURE,
            created_at="2026-05-29T10:00:00Z",
        )

    monkeypatch.setattr(study_router, "save_flashcard", fake_save_flashcard)

    response = harness.client.post(
        "/api/study/flashcards",
        json={
            "learning_path_id": 12,
            "topic": "Graphs",
            "front": "Q",
            "back": "A",
            "source": "transcript",
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json()["flashcard"]["source"] == "transcript"
