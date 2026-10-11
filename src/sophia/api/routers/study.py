"""Authenticated Athena study routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from sophia.api.deps import (
    current_session_record,
    ensure_learning_path_scope,
    get_settings,
    request_session,
    require_csrf,
    require_csrf_learning_path_scope,
    require_learning_path_scope,
)
from sophia.api.provenance import api_provenance
from sophia.api.questions import question_response, require_provenance
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.study import (
    CalibrationBand,
    StudyFlashcardItemResponse,
    StudyFlashcardRequest,
    StudyFlashcardResponse,
    StudyFlashcardSource,
    StudyPacingResponse,
    StudyPhaseAttemptCounts,
    StudyPredictionItemResponse,
    StudyPredictionReasonRequest,
    StudyPredictionRequest,
    StudyPredictionResponse,
    StudyReconciliationItemResponse,
    StudyReconciliationRequest,
    StudyReconciliationResponse,
    StudyReflectionItemResponse,
    StudyReflectionRequest,
    StudyReflectionResponse,
    StudyRequeuedQuestion,
    StudySelfExplanationItemResponse,
    StudySelfExplanationRequest,
    StudySelfExplanationResponse,
    StudySessionCompletionResponse,
    StudySessionItemResponse,
    StudySessionListResponse,
    StudySessionQuestionListResponse,
    StudySessionResponse,
    StudySessionStartRequest,
    StudySessionSummaryResponse,
)
from sophia.api.transactions import TransactionalRoute
from sophia.domain.errors import EngagementPolicyUnmet
from sophia.domain.learning import AttemptPhase as DomainAttemptPhase
from sophia.domain.learning import ContentKind
from sophia.domain.models import FlashcardSource, reconciliation_required
from sophia.services.athena_confidence import record_study_prediction, set_study_prediction_reason
from sophia.services.athena_session import (
    finalize_study_session,
    get_flashcard_course_id,
    get_reflection_pacing,
    get_session_scope,
    get_study_sessions,
    save_flashcard,
    save_flashcard_idempotent,
    save_reflection,
    start_study_session,
    summarize_study_session,
)
from sophia.services.athena_study import save_self_explanation_idempotent
from sophia.services.provenance import get_provenance_map, learner_authored, record_provenance
from sophia.services.study_events import append_event
from sophia.services.study_questions import (
    attempted_question_ids,
    get_session_questions,
    requeued_questions,
    source_titles,
)
from sophia.services.study_reconciliation import (
    previous_reconciliation,
    save_reconciliation,
    session_reconciliation,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.api.schemas.provenance import Provenance
    from sophia.api.sessions import SessionRecord
    from sophia.config import Settings
    from sophia.domain.models import (
        ConfidenceRating,
        SelfExplanation,
        StudentFlashcard,
        StudyReconciliation,
        StudyReflection,
        StudySession,
    )
    from sophia.services.athena_session import SessionScope, StudySessionSummary

router = APIRouter(tags=["study"], route_class=TransactionalRoute)

ATHENA_SESSION_METHOD_COVERAGE: dict[str, dict[str, str]] = {
    "complete_study_session": {
        "rationale": (
            "In-process grading for the CLI study flows, which compute their own "
            "scores. The HTTP path uses finalize_study_session so a client cannot "
            "post scores it invented."
        ),
    },
    "finalize_study_session": {"operation_id": "completeStudySession"},
    "get_study_session": {
        "rationale": "Single-session lookup folded into completion and summary responses.",
    },
    "get_flashcard_course_id": {
        "rationale": "Scope-check lookup for the self-explanation endpoint, not itself a route.",
    },
    "get_reflection_pacing": {
        "rationale": (
            "Pacing evidence read inside completeStudySession's precondition check, "
            "not an endpoint a client should be able to poll."
        ),
    },
    "get_session_scope": {
        "rationale": (
            "Ownership lookup shared by study.py, study_questions.py, and "
            "study_events.py's realtime endpoints — not itself an HTTP endpoint."
        ),
    },
    "get_study_sessions": {"operation_id": "listStudySessions"},
    "run_interactive_session": {
        "rationale": "Rich/CLI orchestration is not a direct HTTP endpoint.",
    },
    "run_interleaved_session": {
        "rationale": "Rich/CLI orchestration is not a direct HTTP endpoint.",
    },
    "save_flashcard": {"operation_id": "saveStudyFlashcard"},
    "save_flashcard_idempotent": {
        "rationale": (
            "The session-scoped idempotent variant saveStudyFlashcard uses when "
            "session_id/request_id are given — same operation, not a separate route."
        ),
    },
    "save_reflection": {"operation_id": "saveStudyReflection"},
    "start_study_session": {"operation_id": "startStudySession"},
    "summarize_study_session": {"operation_id": "getStudySessionSummary"},
}

_DOMAIN_FLASHCARD_SOURCE = {
    StudyFlashcardSource.STUDY: FlashcardSource.STUDY,
    StudyFlashcardSource.TRANSCRIPT: FlashcardSource.LECTURE,
    StudyFlashcardSource.MANUAL: FlashcardSource.MANUAL,
}
_API_FLASHCARD_SOURCE = {
    domain_source: api_source for api_source, domain_source in _DOMAIN_FLASHCARD_SOURCE.items()
}

LearningPathIdQuery = Annotated[int, Query(gt=0)]
SessionIdPath = Annotated[int, Path(gt=0)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/study/pacing",
    response_model=StudyPacingResponse,
    operation_id="getStudyPacing",
)
async def get_study_pacing(request: Request) -> StudyPacingResponse:
    """Serve the pacing floors the study surface enforces in the browser."""
    await current_session_record(request)
    settings = get_settings(request)
    return StudyPacingResponse(
        reflection_min_seconds=settings.study_reflection_min_seconds,
        elaboration_min_chars=settings.elaboration_min_chars,
        prompt_min_dwell_ms=settings.elaboration_min_prompt_dwell_ms,
    )


@router.get(
    "/study/sessions",
    response_model=StudySessionListResponse,
    operation_id="listStudySessions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_study_sessions(
    learning_path_id: LearningPathIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> StudySessionListResponse:
    await require_learning_path_scope(request, learning_path_id)
    sessions = await get_study_sessions(await request_session(request), learning_path_id, topic)
    if topic is not None and not sessions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return StudySessionListResponse(
        learning_path_id=learning_path_id,
        sessions=[_study_session_response(session) for session in sessions],
    )


@router.post(
    "/study/sessions",
    response_model=StudySessionResponse,
    operation_id="startStudySession",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def create_study_session(
    payload: StudySessionStartRequest,
    request: Request,
) -> StudySessionResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    session = await start_study_session(
        await request_session(request),
        payload.learning_path_id,
        payload.topic,
        user_id=auth_session.user.id,
    )
    return StudySessionResponse(session=_study_session_response(session))


@router.post(
    "/study/sessions/{session_id}/complete",
    response_model=StudySessionCompletionResponse,
    operation_id="completeStudySession",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_412_PRECONDITION_FAILED: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def mark_study_session_complete(
    session_id: SessionIdPath,
    request: Request,
) -> StudySessionCompletionResponse:
    """Close a session on scores the server computes from its own attempts.

    This takes no scores from the client on purpose: the endpoint used to
    accept whatever pre/post pair it was handed, which is how a "+0%
    improvement" heuristic could be recorded as fact (see issue #97).
    """
    auth_session = await require_csrf(request)
    db = await request_session(request)
    await _require_session_ownership_by_id(db, auth_session, session_id)
    await _require_reflection_pacing(db, session_id, get_settings(request))
    await _require_reconciliation(db, session_id, auth_session.user.id)
    completed = await finalize_study_session(db, session_id)
    if completed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return StudySessionCompletionResponse(
        session_id=session_id,
        completed=True,
        session=_study_session_response(completed),
    )


@router.get(
    "/study/sessions/{session_id}/summary",
    response_model=StudySessionSummaryResponse,
    operation_id="getStudySessionSummary",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_study_session_summary(
    session_id: SessionIdPath,
    request: Request,
) -> StudySessionSummaryResponse:
    """Serve the reflect route its numbers, so the client computes none of them."""
    auth_session = await current_session_record(request)
    db = await request_session(request)
    await _require_session_ownership_by_id(db, auth_session, session_id)
    user_id = auth_session.user.id
    summary = await summarize_study_session(db, session_id, user_id=user_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _summary_response(
        summary,
        reconciliation=await session_reconciliation(db, session_id, user_id=user_id),
        previous=await previous_reconciliation(db, session_id, user_id=user_id),
    )


@router.get(
    "/study/sessions/{session_id}/questions",
    response_model=StudySessionQuestionListResponse,
    operation_id="listStudySessionQuestions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_study_session_questions(
    session_id: SessionIdPath,
    request: Request,
) -> StudySessionQuestionListResponse:
    """Read a session's question set back instead of generating a new one.

    A reload must not cost another model call, nor hand the learner a
    different set of cards half-way through a session.
    """
    auth_session = await current_session_record(request)
    db = await request_session(request)
    scope = await _require_session_ownership_by_id(db, auth_session, session_id)
    questions = await get_session_questions(db, session_id)
    provenance = await get_provenance_map(
        db,
        ContentKind.QUESTION,
        [question.id for question in questions],
    )
    titles = await source_titles(db, provenance.values())
    return StudySessionQuestionListResponse(
        session_id=session_id,
        learning_path_id=scope.course_id,
        questions=[
            question_response(question, require_provenance(provenance, question), titles)
            for question in questions
        ],
        attempted_question_ids=await attempted_question_ids(db, session_id, auth_session.user.id),
        requeued_questions=[
            StudyRequeuedQuestion(question_id=owed.question_id, attempts=owed.attempts)
            for owed in await requeued_questions(db, session_id, auth_session.user.id)
        ],
    )


@router.post(
    "/study/flashcards",
    response_model=StudyFlashcardResponse,
    operation_id="saveStudyFlashcard",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def create_study_flashcard(
    payload: StudyFlashcardRequest,
    request: Request,
) -> StudyFlashcardResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)

    if payload.session_id is not None and payload.request_id is not None:
        await _require_session_ownership(
            db, auth_session, payload.learning_path_id, payload.session_id
        )
        flashcard, is_new = await save_flashcard_idempotent(
            db,
            payload.learning_path_id,
            payload.topic,
            payload.front,
            payload.back,
            _DOMAIN_FLASHCARD_SOURCE[payload.source].value,
            session_id=payload.session_id,
            user_id=auth_session.user.id,
            request_id=payload.request_id,
        )
        if is_new:
            await append_event(
                db,
                session_id=payload.session_id,
                course_id=payload.learning_path_id,
                actor_id=auth_session.user.id,
                event_type="flashcard_saved",
                payload={"flashcard_id": flashcard.id},
                request_id=payload.request_id,
            )
    else:
        flashcard = await save_flashcard(
            db,
            payload.learning_path_id,
            payload.topic,
            payload.front,
            payload.back,
            _DOMAIN_FLASHCARD_SOURCE[payload.source].value,
        )

    provenance = learner_authored(
        ContentKind.FLASHCARD,
        str(flashcard.id),
        flashcard.course_id,
        generated_at=flashcard.created_at,
    )
    await record_provenance(db, provenance)
    return StudyFlashcardResponse(
        flashcard=_flashcard_response(flashcard, api_provenance(provenance)),
    )


@router.post(
    "/study/predictions",
    response_model=StudyPredictionResponse,
    operation_id="recordStudyPrediction",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_study_prediction(
    payload: StudyPredictionRequest,
    request: Request,
) -> StudyPredictionResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    rating, is_new = await record_study_prediction(
        db,
        payload.topic,
        payload.learning_path_id,
        payload.rating,
        session_id=payload.session_id,
        user_id=auth_session.user.id,
        request_id=payload.request_id,
        reason=payload.reason,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="prediction_recorded",
            payload={"topic": payload.topic, "predicted": rating.predicted},
            request_id=payload.request_id,
        )
    return StudyPredictionResponse(
        prediction=_prediction_response(rating, payload.learning_path_id)
    )


@router.put(
    "/study/sessions/{session_id}/prediction/reason",
    response_model=StudyPredictionResponse,
    operation_id="saveStudyPredictionReason",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def save_study_prediction_reason(
    session_id: SessionIdPath,
    payload: StudyPredictionReasonRequest,
    request: Request,
) -> StudyPredictionResponse:
    """Store the "because…" line with the prediction the session already holds.

    A 404 until the learner has predicted: there is no rating to attach it to.
    """
    auth_session = await require_csrf(request)
    db = await request_session(request)
    scope = await _require_session_ownership_by_id(db, auth_session, session_id)
    rating = await set_study_prediction_reason(
        db, session_id, payload.reason, user_id=auth_session.user.id
    )
    if rating is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return StudyPredictionResponse(prediction=_prediction_response(rating, scope.course_id))


@router.post(
    "/study/self-explanations",
    response_model=StudySelfExplanationResponse,
    operation_id="saveStudySelfExplanation",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_self_explanation(
    payload: StudySelfExplanationRequest,
    request: Request,
) -> StudySelfExplanationResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    flashcard_course_id = await get_flashcard_course_id(db, payload.flashcard_id)
    if flashcard_course_id is None or flashcard_course_id != payload.learning_path_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    explanation, is_new = await save_self_explanation_idempotent(
        db,
        payload.flashcard_id,
        payload.student_explanation,
        payload.scaffold_level,
        session_id=payload.session_id,
        user_id=auth_session.user.id,
        request_id=payload.request_id,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="self_explanation_recorded",
            payload={"flashcard_id": explanation.flashcard_id},
            request_id=payload.request_id,
        )
    return StudySelfExplanationResponse(self_explanation=_self_explanation_response(explanation))


@router.post(
    "/study/reflections",
    response_model=StudyReflectionResponse,
    operation_id="saveStudyReflection",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_reflection(
    payload: StudyReflectionRequest,
    request: Request,
) -> StudyReflectionResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    reflection, is_new = await save_reflection(
        db,
        payload.session_id,
        payload.learning_path_id,
        auth_session.user.id,
        payload.prompt,
        payload.reflection_text,
        request_id=payload.request_id,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="reflection_recorded",
            payload={"prompt": payload.prompt},
            request_id=payload.request_id,
        )
    return StudyReflectionResponse(reflection=_reflection_response(reflection))


@router.post(
    "/study/reconciliations",
    response_model=StudyReconciliationResponse,
    operation_id="saveStudyReconciliation",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_412_PRECONDITION_FAILED: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_reconciliation(
    payload: StudyReconciliationRequest,
    request: Request,
) -> StudyReconciliationResponse:
    """Record what explains the gap between the learner's prediction and score."""
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    reconciliation, is_new = await save_reconciliation(
        db,
        payload.session_id,
        payload.learning_path_id,
        auth_session.user.id,
        payload.reconciliation_text,
        request_id=payload.request_id,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="reconciliation_recorded",
            payload={"band": reconciliation.band.value},
            request_id=payload.request_id,
        )
    return StudyReconciliationResponse(reconciliation=_reconciliation_response(reconciliation))


async def _require_session_ownership(
    db: AsyncSession,
    auth_session: SessionRecord,
    learning_path_id: int,
    session_id: int,
) -> SessionScope:
    """A session started before study realtime tracked ownership has no user_id
    to match, so it can never pass this check — see get_session_scope."""
    scope = await _require_session_ownership_by_id(db, auth_session, session_id)
    if scope.course_id != learning_path_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return scope


async def _require_session_ownership_by_id(
    db: AsyncSession,
    auth_session: SessionRecord,
    session_id: int,
) -> SessionScope:
    """Ownership check for the routes that carry no learning path of their own.

    The learning path comes from the stored session rather than the request, so
    these cannot be answered with a scope check alone: without matching the
    owner, a learner sharing a learning path could complete or read somebody
    else's session (the gap issue #97's audit left open on this endpoint).
    """
    scope = await get_session_scope(db, session_id)
    if scope is None or scope.user_id != auth_session.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_learning_path_scope(auth_session, scope.course_id)
    return scope


async def _require_reflection_pacing(
    db: AsyncSession,
    session_id: int,
    settings: Settings,
) -> None:
    """Refuse to close a session that skipped the reflection or rushed it.

    Serving the floor was never enough on its own: a client that never renders
    the countdown can still POST here, which is exactly the abuse case issue
    #98 names. Both timestamps compared are the server's own, so the gap cannot
    be shortened from the browser.
    """
    pacing = await get_reflection_pacing(db, session_id)
    if pacing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    elapsed = pacing.reflection_seconds
    floor = settings.study_reflection_min_seconds
    if elapsed is None:
        msg = "session completed without a reflection"
        raise EngagementPolicyUnmet(msg, {"required": "reflection", "reflection_seconds": 0})
    if elapsed < floor:
        msg = "session completed before the reflection floor elapsed"
        raise EngagementPolicyUnmet(
            msg,
            {
                "required": "reflection_pacing",
                "reflection_seconds": int(elapsed),
                "reflection_min_seconds": floor,
            },
        )


async def _require_reconciliation(db: AsyncSession, session_id: int, user_id: str) -> None:
    """Refuse to close a session whose prediction missed until the learner says why.

    The same abuse case as the reflection: a client that never renders the
    prompt can still POST here. The band is computed now, by the server, from
    the same attempts the completion is about to score.
    """
    summary = await summarize_study_session(db, session_id, user_id=user_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not reconciliation_required(summary.band):
        return
    if await session_reconciliation(db, session_id, user_id=user_id) is not None:
        return
    msg = "session completed without reconciling the prediction with the result"
    raise EngagementPolicyUnmet(msg, {"required": "reconciliation", "band": summary.band.value})


def _summary_response(
    summary: StudySessionSummary,
    *,
    reconciliation: StudyReconciliation | None,
    previous: StudyReconciliation | None,
) -> StudySessionSummaryResponse:
    predicted = summary.predicted
    measured = summary.measured
    return StudySessionSummaryResponse(
        session=_study_session_response(summary.session),
        attempts=StudyPhaseAttemptCounts(
            pre_test=summary.attempts_by_phase[DomainAttemptPhase.PRE_TEST],
            practice=summary.attempts_by_phase[DomainAttemptPhase.PRACTICE],
            post_test=summary.attempts_by_phase[DomainAttemptPhase.POST_TEST],
        ),
        practice_score=summary.practice_score,
        predicted=predicted,
        prediction_reason=summary.prediction_reason,
        measured=measured,
        calibration_delta=(None if predicted is None or measured is None else measured - predicted),
        band=CalibrationBand(summary.band.value),
        legacy_scored=summary.legacy_scored,
        reflected=summary.reflected,
        reconciliation_required=reconciliation_required(summary.band),
        reconciliation=None if reconciliation is None else _reconciliation_response(reconciliation),
        previous_reconciliation=None if previous is None else _reconciliation_response(previous),
    )


def _study_session_response(session: StudySession) -> StudySessionItemResponse:
    return StudySessionItemResponse(
        id=session.id,
        learning_path_id=session.course_id,
        topic=session.topic,
        pre_test_score=session.pre_test_score,
        post_test_score=session.post_test_score,
        started_at=session.started_at,
        completed_at=session.completed_at,
        improvement=session.improvement,
    )


def _flashcard_response(
    flashcard: StudentFlashcard,
    provenance: Provenance,
) -> StudyFlashcardItemResponse:
    return StudyFlashcardItemResponse(
        id=flashcard.id,
        learning_path_id=flashcard.course_id,
        topic=flashcard.topic,
        front=flashcard.front,
        back=flashcard.back,
        source=_API_FLASHCARD_SOURCE[flashcard.source],
        created_at=flashcard.created_at,
        provenance=provenance,
    )


def _prediction_response(
    rating: ConfidenceRating,
    learning_path_id: int,
) -> StudyPredictionItemResponse:
    return StudyPredictionItemResponse(
        learning_path_id=learning_path_id,
        topic=rating.topic,
        predicted=rating.predicted,
        reason=rating.reason,
        rated_at=rating.rated_at,
    )


def _self_explanation_response(
    explanation: SelfExplanation,
) -> StudySelfExplanationItemResponse:
    return StudySelfExplanationItemResponse(
        id=explanation.id,
        flashcard_id=explanation.flashcard_id,
        student_explanation=explanation.student_explanation,
        scaffold_level=explanation.scaffold_level,
        created_at=explanation.created_at,
    )


def _reflection_response(reflection: StudyReflection) -> StudyReflectionItemResponse:
    return StudyReflectionItemResponse(
        id=reflection.id,
        session_id=reflection.session_id,
        learning_path_id=reflection.course_id,
        prompt=reflection.prompt,
        reflection_text=reflection.reflection_text,
        created_at=reflection.created_at,
    )


def _reconciliation_response(
    reconciliation: StudyReconciliation,
) -> StudyReconciliationItemResponse:
    return StudyReconciliationItemResponse(
        id=reconciliation.id,
        session_id=reconciliation.session_id,
        learning_path_id=reconciliation.course_id,
        predicted=reconciliation.predicted,
        measured=reconciliation.measured,
        band=CalibrationBand(reconciliation.band.value),
        reconciliation_text=reconciliation.reconciliation_text,
        created_at=reconciliation.created_at,
    )
