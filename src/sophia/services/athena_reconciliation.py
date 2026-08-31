"""Topic reconciliation engine — matches manual predictions against Moodle topics."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.infra.schema import topic_mappings, topic_reconciliations

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

FUZZY_MATCH_THRESHOLD = 0.6


@dataclass(frozen=True)
class ReconciliationResult:
    matched: list[tuple[str, str, float]]  # (manual_topic, moodle_topic, similarity)
    unmatched_manual: list[str]
    new_moodle: list[str]


async def reconcile_manual_topics(
    session: AsyncSession,
    course_id: int,
) -> ReconciliationResult:
    """Match manual topic predictions against Moodle-sourced topics using fuzzy matching."""
    manual = await _load_topics(session, course_id, manual=True)
    moodle = await _load_topics(session, course_id, manual=False)

    if not manual:
        return ReconciliationResult(matched=[], unmatched_manual=[], new_moodle=[])

    if not moodle:
        return ReconciliationResult(matched=[], unmatched_manual=list(manual), new_moodle=[])

    matched: list[tuple[str, str, float]] = []
    unmatched_manual: list[str] = []
    claimed_moodle: set[str] = set()

    for m_topic in manual:
        best_topic, best_score = _find_best_match(m_topic, moodle)
        if best_score >= FUZZY_MATCH_THRESHOLD:
            matched.append((m_topic, best_topic, best_score))
            claimed_moodle.add(best_topic)
        else:
            unmatched_manual.append(m_topic)

    new_moodle = [t for t in moodle if t not in claimed_moodle]

    await _persist_matches(session, course_id, matched)

    log.info(
        "topics_reconciled",
        course_id=course_id,
        matched=len(matched),
        unmatched=len(unmatched_manual),
        new_moodle=len(new_moodle),
    )
    return ReconciliationResult(
        matched=matched,
        unmatched_manual=unmatched_manual,
        new_moodle=new_moodle,
    )


def format_reconciliation_message(result: ReconciliationResult) -> str:
    """Format an honest gap-framing message from reconciliation results."""
    if not result.matched and not result.unmatched_manual and not result.new_moodle:
        return ""

    parts: list[str] = ["Your predictions have been matched to course topics."]

    if result.matched:
        n = len(result.matched)
        parts.append(
            f"{n} of your topic prediction{'s' if n != 1 else ''} matched actual course content."
        )

    if result.unmatched_manual:
        n = len(result.unmatched_manual)
        parts.append(
            f"You expected {n} topic{'s' if n != 1 else ''} the course doesn't cover"
            " — these are preserved as your original predictions."
        )

    if result.new_moodle:
        n = len(result.new_moodle)
        if n <= 5:
            topics = ", ".join(result.new_moodle)
            parts.append(
                f"The course covers {n} topic{'s' if n != 1 else ''} you hadn't predicted"
                f" — here's what surprised you: {topics}"
            )
        else:
            parts.append(f"The course covers {n} topics you hadn't predicted.")

    return " ".join(parts)


# ── Internal helpers ───────────────────────────────────────────────────────


async def _load_topics(
    session: AsyncSession,
    course_id: int,
    *,
    manual: bool,
) -> list[str]:
    source = topic_mappings.c.source
    query = select(topic_mappings.c.topic).where(
        topic_mappings.c.course_id == course_id,
        source == "manual" if manual else source != "manual",
    )
    return list((await session.scalars(query)).all())


def _find_best_match(topic: str, candidates: list[str]) -> tuple[str, float]:
    best_topic = ""
    best_score = 0.0
    lower = topic.lower()
    for candidate in candidates:
        score = SequenceMatcher(None, lower, candidate.lower()).ratio()
        if score > best_score:
            best_score = score
            best_topic = candidate
    return best_topic, best_score


async def _persist_matches(
    session: AsyncSession,
    course_id: int,
    matched: list[tuple[str, str, float]],
) -> None:
    for manual_topic, moodle_topic, similarity in matched:
        await session.execute(
            pg_insert(topic_reconciliations)
            .values(
                manual_topic=manual_topic,
                moodle_topic=moodle_topic,
                course_id=course_id,
                similarity=similarity,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    topic_reconciliations.c.manual_topic,
                    topic_reconciliations.c.course_id,
                ]
            )
        )
