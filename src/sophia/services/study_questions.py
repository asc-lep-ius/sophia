"""Generated questions and the attempts made against them.

Questions are persisted before they are served because the engagement policy has
to be the one the server issued. If the answering client echoed the policy back,
satisfying it would be a matter of editing a JSON body.

Only the open-response format is generated today; the multiple-choice and cloze
variants of the API union are reserved for the formats a later phase adds.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.errors import TopicExtractionError
from sophia.domain.learning import (
    ClozeSegment,
    ContentKind,
    ContentLanguage,
    ContentProvenance,
    ElaborationPolicy,
    GeneratedQuestion,
    LearningEventType,
    ProvenanceAgent,
    QuestionAttempt,
    QuestionKind,
    QuestionOption,
    StoredContentOrigin,
)
from sophia.infra.schema import generated_questions, question_attempts
from sophia.services.athena_confidence import (
    get_confidence_ratings,
    get_topic_difficulty_level,
)
from sophia.services.athena_study import generate_study_questions
from sophia.services.hermes_setup import load_hermes_config
from sophia.services.provenance import record_provenance

if TYPE_CHECKING:
    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

FALLBACK_QUESTION = "Explain the concept of {topic} in your own words."
FALLBACK_GENERATOR_REF = "fallback-template"

ELABORATION_REQUIRED_EVENTS = (
    LearningEventType.PROMPT_SHOWN,
    LearningEventType.PREDICTION_MADE,
    LearningEventType.ELABORATION_WRITTEN,
)

SELF_RATING_SCORES: dict[int, float] = {1: 0.0, 2: 0.3, 3: 0.7, 4: 1.0}
"""Post-reveal self-grade -> score. Mirrors the values of
``gui/services/review_service.RATING_SCORES`` (the same Again/Hard/Good/Easy
scale already used for flashcard review) but is not imported from there:
``services`` must not depend on ``gui``, and this is a distinct domain concept
(grading an open-response question attempt, not scheduling a flashcard review).
"""


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """A saved attempt plus whether this request created it.

    ``is_new`` is False when a duplicate ``request_id`` matched an existing row:
    the attempt returned is the one from the original submission, and callers
    must not repeat side effects (calibration write, event-log append) that
    already ran for it.
    """

    attempt: QuestionAttempt
    is_new: bool


async def generate_and_store_questions(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    *,
    count: int,
    content_language: ContentLanguage,
    policy: ElaborationPolicy,
    user_id: str | None = None,
) -> list[GeneratedQuestion]:
    """Generate open-response questions, persist them, and record provenance.

    Difficulty adapts to the learner's own confidence in the topic, mirroring
    the interactive session rather than serving one fixed band to everybody —
    ``user_id`` is what makes it *that learner's* confidence rather than
    whichever confidence rating happens to be newest across everyone sharing
    the course.
    """
    difficulty = await _adaptive_difficulty(app, session, course_id, topic, user_id=user_id)
    prompts, generator_ref = await _generate_prompts(
        app,
        session,
        course_id,
        topic,
        count=count,
        difficulty=difficulty,
    )
    generated_at = datetime.now(UTC).isoformat()

    questions = [
        GeneratedQuestion(
            id=str(uuid.uuid4()),
            course_id=course_id,
            topic=topic,
            kind=QuestionKind.OPEN_RESPONSE,
            prompt=prompt,
            difficulty=difficulty,
            content_language=content_language,
            elaboration_policy=policy,
        )
        for prompt in prompts
    ]

    for question in questions:
        await _insert_question(session, question)
        await record_provenance(
            session,
            ContentProvenance(
                content_kind=ContentKind.QUESTION,
                content_id=question.id,
                course_id=course_id,
                origin=StoredContentOrigin.TUWEL,
                generated_by=ProvenanceAgent.MODEL,
                generator_ref=generator_ref,
                generated_at=generated_at,
            ),
        )

    log.info("study_questions_generated", course_id=course_id, topic=topic, count=len(questions))
    return questions


async def get_question(
    session: AsyncSession,
    question_id: str,
) -> GeneratedQuestion | None:
    """Load one persisted question by id."""
    row = (
        await session.execute(
            select(generated_questions).where(generated_questions.c.id == question_id)
        )
    ).one_or_none()
    return None if row is None else _row_to_question(row)


async def save_attempt(
    session: AsyncSession,
    course_id: int,
    question_id: str,
    user_id: str,
    answer_text: str,
    confidence: int | None,
    *,
    session_id: int,
    request_id: str,
    self_rating: int,
) -> AttemptResult:
    """Persist a learner's self-graded answer, idempotently.

    The score comes from the learner's own post-reveal self-assessment
    (``self_rating``, the same Again/Hard/Good/Easy scale flashcard review
    already uses) rather than automated grading: nothing in this codebase stores
    an expected answer or rubric to grade ``answer_text`` against. A retried
    ``request_id`` returns the original attempt (with ``is_new=False``) instead
    of inserting a second row, relying on the unique constraint on
    ``(org_id, session_id, user_id, request_id)`` rather than an in-process map,
    so it stays correct across worker restarts and concurrent retries.
    """
    score = SELF_RATING_SCORES[self_rating]
    submitted_at = datetime.now(UTC)
    inserted = (
        await session.execute(
            pg_insert(question_attempts)
            .values(
                course_id=course_id,
                question_id=question_id,
                user_id=user_id,
                answer_text=answer_text,
                confidence=confidence,
                submitted_at=submitted_at,
                session_id=session_id,
                request_id=request_id,
                self_rating=self_rating,
                score=score,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    question_attempts.c.org_id,
                    question_attempts.c.session_id,
                    question_attempts.c.user_id,
                    question_attempts.c.request_id,
                ],
            )
            .returning(question_attempts.c.id)
        )
    ).one_or_none()

    if inserted is not None:
        return AttemptResult(
            attempt=QuestionAttempt(
                id=inserted.id,
                course_id=course_id,
                question_id=question_id,
                user_id=user_id,
                answer_text=answer_text,
                confidence=confidence,
                submitted_at=submitted_at.isoformat(),
                session_id=session_id,
                request_id=request_id,
                self_rating=self_rating,
                score=score,
            ),
            is_new=True,
        )

    existing = (
        await session.execute(
            select(question_attempts).where(
                question_attempts.c.session_id == session_id,
                question_attempts.c.user_id == user_id,
                question_attempts.c.request_id == request_id,
            )
        )
    ).one()
    return AttemptResult(attempt=_row_to_attempt(existing), is_new=False)


def _row_to_attempt(row: Row[tuple[object, ...]]) -> QuestionAttempt:
    return QuestionAttempt(
        id=row.id,
        course_id=row.course_id,
        question_id=row.question_id,
        user_id=row.user_id,
        answer_text=row.answer_text,
        confidence=row.confidence,
        submitted_at=row.submitted_at.isoformat() if row.submitted_at else "",
        session_id=row.session_id,
        request_id=row.request_id,
        self_rating=row.self_rating,
        score=row.score,
    )


def default_elaboration_policy(
    *,
    min_elaboration_chars: int,
    min_prompt_dwell_ms: int,
) -> ElaborationPolicy:
    """The elaboration demand attached to every generated open-response question."""
    return ElaborationPolicy(
        required_event_types=ELABORATION_REQUIRED_EVENTS,
        min_elaboration_chars=min_elaboration_chars,
        min_prompt_dwell_ms=min_prompt_dwell_ms,
    )


async def _adaptive_difficulty(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    *,
    user_id: str | None,
) -> str:
    ratings = await get_confidence_ratings(session, course_id, user_id=user_id)
    topic_rating = next((rating for rating in ratings if rating.topic == topic), None)
    return get_topic_difficulty_level(topic_rating.predicted if topic_rating else None).value


async def _generate_prompts(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    *,
    count: int,
    difficulty: str,
) -> tuple[list[str], str]:
    """Return the prompts and the generator that actually produced them.

    The generator is recorded as provenance, so a template fallback must not be
    attributed to a model the learner never went near.
    """
    try:
        prompts = await generate_study_questions(
            app,
            session,
            course_id,
            topic,
            count=count,
            difficulty=difficulty,
        )
    except TopicExtractionError:
        log.warning("study_question_generation_failed", course_id=course_id, topic=topic)
        return [FALLBACK_QUESTION.format(topic=topic)] * count, FALLBACK_GENERATOR_REF
    return prompts, _generator_ref(app)


def _generator_ref(app: AppContainer) -> str:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        return FALLBACK_GENERATOR_REF
    return f"{config.llm.provider.value}:{config.llm.model}"


async def _insert_question(session: AsyncSession, question: GeneratedQuestion) -> None:
    policy = question.elaboration_policy
    await session.execute(
        insert(generated_questions).values(
            id=question.id,
            course_id=question.course_id,
            topic=question.topic,
            kind=question.kind.value,
            prompt=question.prompt,
            difficulty=question.difficulty,
            content_language=question.content_language.value,
            options=json.dumps([option.model_dump() for option in question.options]),
            segments=json.dumps([segment.model_dump() for segment in question.segments]),
            elaboration_policy=None if policy is None else policy.model_dump_json(),
        )
    )


def _row_to_question(row: Row[tuple[object, ...]]) -> GeneratedQuestion:
    return GeneratedQuestion(
        id=row.id,
        course_id=row.course_id,
        topic=row.topic,
        kind=QuestionKind(row.kind),
        prompt=row.prompt or "",
        difficulty=row.difficulty,
        content_language=ContentLanguage(row.content_language),
        options=_decode_options(row.options),
        segments=_decode_segments(row.segments),
        elaboration_policy=(
            None
            if row.elaboration_policy is None
            else ElaborationPolicy.model_validate_json(row.elaboration_policy)
        ),
    )


def _decode_options(raw: object) -> tuple[QuestionOption, ...]:
    return tuple(QuestionOption.model_validate(item) for item in _decode_list(raw))


def _decode_segments(raw: object) -> tuple[ClozeSegment, ...]:
    return tuple(ClozeSegment.model_validate(item) for item in _decode_list(raw))


def _decode_list(raw: object) -> list[object]:
    if not isinstance(raw, str) or not raw:
        return []
    decoded: object = json.loads(raw)
    return cast("list[object]", decoded) if isinstance(decoded, list) else []
