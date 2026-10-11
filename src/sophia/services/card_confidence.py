"""Per-card calibration: how often an answer the learner was sure of met Again.

The session's prediction is one judgement about a topic. Each card also asks
how sure the learner is of their own answer, before its reveal, and that is the
judgement that can be checked item by item: a sure answer they then graded
Again is a confident error, the kind most worth correcting (Butterfield &
Metcalfe 2001).

Only attempts that carry a confidence count. Attempts from before the card
asked for one have none, and treating them as unsure would invent judgements
the learner never made, so they are counted apart and reported as left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select

from sophia.infra.schema import generated_questions, question_attempts
from sophia.services.study_questions import AGAIN_RATING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SURE_CONFIDENCE = 4
"""Sure or Certain on the 1-5 scale. Mirrors ``SURE_CONFIDENCE`` in the study
store (``frontend/src/lib/study/session.svelte.ts``), which flags the same
answers on the card when they are graded Again or Hard."""


@dataclass(frozen=True, slots=True)
class TopicCardConfidence:
    """One topic's answers that carry a confidence."""

    topic: str
    rated: int
    sure: int
    sure_again: int


@dataclass(frozen=True, slots=True)
class CardConfidence:
    """Every topic with a rated answer, and how many answers had no rating."""

    topics: list[TopicCardConfidence]
    unrated: int


async def get_card_confidence(
    session: AsyncSession,
    course_id: int,
    user_id: str,
) -> CardConfidence:
    """Count one learner's sure answers per topic, and the Agains among them."""
    sure = question_attempts.c.confidence >= SURE_CONFIDENCE
    rows = (
        await session.execute(
            select(
                generated_questions.c.topic,
                func.count().label("answers"),
                func.count(question_attempts.c.confidence).label("rated"),
                func.count().filter(sure).label("sure"),
                func.count()
                .filter(and_(sure, question_attempts.c.self_rating == AGAIN_RATING))
                .label("sure_again"),
            )
            .select_from(
                question_attempts.join(
                    generated_questions,
                    generated_questions.c.id == question_attempts.c.question_id,
                )
            )
            .where(
                question_attempts.c.course_id == course_id,
                question_attempts.c.user_id == user_id,
            )
            .group_by(generated_questions.c.topic)
            .order_by(generated_questions.c.topic)
        )
    ).all()
    return CardConfidence(
        topics=[
            TopicCardConfidence(
                topic=row.topic,
                rated=row.rated,
                sure=row.sure,
                sure_again=row.sure_again,
            )
            for row in rows
            if row.rated > 0
        ],
        unrated=sum(row.answers - row.rated for row in rows),
    )
