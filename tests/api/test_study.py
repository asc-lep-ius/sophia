"""Study API route tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from sophia.api.routers import study as study_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import FlashcardSource, StudentFlashcard, StudySession
from sophia.services.athena_session import SessionScope

from ._session_helpers import FakeAppContainer, build_harness, csrf_headers, login

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer


async def noop_record_provenance(_db: object, _provenance: object) -> None:
    """The flashcard route tests exercise the route, not provenance persistence."""


def _fake_session_owner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    course_id: int,
    user_id: str | None,
) -> None:
    """Answer the ownership lookup the session-scoped routes make first."""

    async def fake_get_session_scope(_db: object, _session_id: int) -> SessionScope:
        return SessionScope(course_id=course_id, user_id=user_id)

    monkeypatch.setattr(study_router, "get_session_scope", fake_get_session_scope)


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        learning_path_id=str(learning_path_id),
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
        *,
        user_id: str | None = None,
    ) -> StudySession:
        assert db is fake_app.db
        assert course_id == 12
        assert topic == "Graphs"
        assert user_id == "learner"
        return StudySession(
            id=8,
            course_id=12,
            topic="Graphs",
            started_at="2026-05-26T13:00:00Z",
            user_id=user_id,
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

    response = harness.client.post("/api/study/sessions/8/complete")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_complete_study_session_returns_the_server_scored_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    calls: list[tuple[object, int]] = []

    async def fake_finalize_study_session(db: object, session_id: int) -> StudySession:
        calls.append((db, session_id))
        return StudySession(
            id=session_id,
            course_id=12,
            topic="Graphs",
            pre_test_score=0.3,
            post_test_score=0.7,
            started_at="2026-09-04T10:00:00+00:00",
            completed_at="2026-09-04T10:40:00+00:00",
        )

    _fake_session_owner(monkeypatch, course_id=12, user_id="learner")
    monkeypatch.setattr(study_router, "finalize_study_session", fake_finalize_study_session)

    response = harness.client.post(
        "/api/study/sessions/8/complete",
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == 8
    assert body["completed"] is True
    assert body["session"]["pre_test_score"] == 0.3
    assert body["session"]["post_test_score"] == 0.7
    assert body["session"]["improvement"] == pytest.approx(0.4)
    assert calls == [(fake_app.db, 8)]


def test_complete_study_session_rejects_a_session_owned_by_another_learner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The learning-path scope check alone let a same-tenant learner close
    somebody else's session — the gap issue #97's audit left open here."""
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(),
    )
    login(harness)
    calls: list[int] = []

    async def fake_finalize_study_session(_db: object, session_id: int) -> StudySession | None:
        calls.append(session_id)
        return None

    _fake_session_owner(monkeypatch, course_id=12, user_id="somebody-else")
    monkeypatch.setattr(study_router, "finalize_study_session", fake_finalize_study_session)

    response = harness.client.post(
        "/api/study/sessions/8/complete",
        headers=csrf_headers(harness),
    )

    assert response.status_code == 404
    assert calls == []


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
    monkeypatch.setattr(study_router, "record_provenance", noop_record_provenance)

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
            "provenance": {
                "origin": "lms",
                "generated_by": "learner",
                "generator_ref": None,
                "generated_at": "2026-05-26T14:00:00Z",
                "verified_by": None,
                "verified_at": None,
                "source_spans": [],
            },
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
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(12),
    )
    login(harness)
    calls: list[int] = []

    async def fake_finalize_study_session(_db: object, session_id: int) -> StudySession | None:
        calls.append(session_id)
        return None

    _fake_session_owner(monkeypatch, course_id=99, user_id="learner")
    monkeypatch.setattr(study_router, "finalize_study_session", fake_finalize_study_session)

    response = harness.client.post(
        "/api/study/sessions/8/complete",
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
    monkeypatch.setattr(study_router, "record_provenance", noop_record_provenance)

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


def test_study_pacing_serves_the_server_configured_floors() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.get("/api/study/pacing")

    assert response.status_code == 200
    assert response.json() == {
        "reflection_min_seconds": harness.settings.study_reflection_min_seconds,
        "elaboration_min_chars": harness.settings.elaboration_min_chars,
        "prompt_min_dwell_ms": harness.settings.elaboration_min_prompt_dwell_ms,
    }


def test_study_pacing_requires_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    assert harness.client.get("/api/study/pacing").status_code == 401
