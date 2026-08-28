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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import structlog

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
from sophia.services.athena_confidence import (
    get_confidence_ratings,
    get_topic_difficulty_level,
)
from sophia.services.athena_study import generate_study_questions
from sophia.services.hermes_setup import load_hermes_config
from sophia.services.provenance import record_provenance

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiosqlite

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

FALLBACK_QUESTION = "Explain the concept of {topic} in your own words."
FALLBACK_GENERATOR_REF = "fallback-template"

ELABORATION_REQUIRED_EVENTS = (
    LearningEventType.PROMPT_SHOWN,
    LearningEventType.PREDICTION_MADE,
    LearningEventType.ELABORATION_WRITTEN,
)

_QUESTION_COLUMNS = (
    "id, course_id, topic, kind, prompt, difficulty, content_language, "
    "options, segments, elaboration_policy"
)


async def generate_and_store_questions(
    app: AppContainer,
    course_id: int,
    topic: str,
    *,
    count: int,
    content_language: ContentLanguage,
    policy: ElaborationPolicy,
) -> list[GeneratedQuestion]:
    """Generate open-response questions, persist them, and record provenance.

    Difficulty adapts to the learner's own confidence in the topic, mirroring
    the interactive session rather than serving one fixed band to everybody.
    """
    difficulty = await _adaptive_difficulty(app, course_id, topic)
    prompts, generator_ref = await _generate_prompts(
        app,
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
        await _insert_question(app.db, question)
        await record_provenance(
            app.db,
            ContentProvenance(
                content_kind=ContentKind.QUESTION,
                content_id=question.id,
                course_id=course_id,
                origin=StoredContentOrigin.TUWEL,
                generated_by=ProvenanceAgent.MODEL,
                generator_ref=generator_ref,
                generated_at=generated_at,
            ),
            commit=False,
        )
    await app.db.commit()

    log.info("study_questions_generated", course_id=course_id, topic=topic, count=len(questions))
    return questions


async def get_question(
    db: aiosqlite.Connection,
    question_id: str,
) -> GeneratedQuestion | None:
    """Load one persisted question by id."""
    cursor = await db.execute(
        f"SELECT {_QUESTION_COLUMNS} FROM generated_questions WHERE id = ?",
        (question_id,),
    )
    row = cast("tuple[object, ...] | None", await cursor.fetchone())
    return None if row is None else _row_to_question(row)


async def save_attempt(
    db: aiosqlite.Connection,
    course_id: int,
    question_id: str,
    user_id: str,
    answer_text: str,
    confidence: int | None,
) -> QuestionAttempt:
    """Persist a learner's answer.

    No score is written: grading moves server-side in the study realtime phase,
    and guessing a score here would bake in the very defect that phase fixes.
    """
    submitted_at = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "INSERT INTO question_attempts ("
        "course_id, question_id, user_id, answer_text, confidence, submitted_at) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (course_id, question_id, user_id, answer_text, confidence, submitted_at),
    )
    row = cast("tuple[int, ...] | None", await cursor.fetchone())
    if row is None:
        msg = "attempt insert returned no row"
        raise RuntimeError(msg)
    await db.commit()

    return QuestionAttempt(
        id=row[0],
        course_id=course_id,
        question_id=question_id,
        user_id=user_id,
        answer_text=answer_text,
        confidence=confidence,
        submitted_at=submitted_at,
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


async def _adaptive_difficulty(app: AppContainer, course_id: int, topic: str) -> str:
    ratings = await get_confidence_ratings(app.db, course_id)
    topic_rating = next((rating for rating in ratings if rating.topic == topic), None)
    return get_topic_difficulty_level(topic_rating.predicted if topic_rating else None).value


async def _generate_prompts(
    app: AppContainer,
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


async def _insert_question(db: aiosqlite.Connection, question: GeneratedQuestion) -> None:
    policy = question.elaboration_policy
    await db.execute(
        "INSERT INTO generated_questions ("
        "id, course_id, topic, kind, prompt, difficulty, content_language, "
        "options, segments, elaboration_policy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            question.id,
            question.course_id,
            question.topic,
            question.kind.value,
            question.prompt,
            question.difficulty,
            question.content_language.value,
            json.dumps([option.model_dump() for option in question.options]),
            json.dumps([segment.model_dump() for segment in question.segments]),
            None if policy is None else policy.model_dump_json(),
        ),
    )


def _row_to_question(row: tuple[object, ...]) -> GeneratedQuestion:
    raw_policy = row[9]
    return GeneratedQuestion(
        id=str(row[0]),
        course_id=int(cast("int", row[1])),
        topic=str(row[2]),
        kind=QuestionKind(str(row[3])),
        prompt=str(row[4] or ""),
        difficulty=str(row[5]),
        content_language=ContentLanguage(str(row[6])),
        options=_decode_options(row[7]),
        segments=_decode_segments(row[8]),
        elaboration_policy=(
            None if raw_policy is None else ElaborationPolicy.model_validate_json(str(raw_policy))
        ),
    )


def _decode_options(raw: object) -> tuple[QuestionOption, ...]:
    return tuple(QuestionOption.model_validate(item) for item in _decode_list(raw))


def _decode_segments(raw: object) -> tuple[ClozeSegment, ...]:
    return tuple(ClozeSegment.model_validate(item) for item in _decode_list(raw))


def _decode_list(raw: object) -> Sequence[object]:
    if not isinstance(raw, str) or not raw:
        return ()
    decoded = cast("object", json.loads(raw))
    return cast("Sequence[object]", decoded) if isinstance(decoded, list) else ()
