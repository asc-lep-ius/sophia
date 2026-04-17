"""Topic reconciliation engine — matches manual predictions against Moodle topics."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

log = structlog.get_logger()

FUZZY_MATCH_THRESHOLD = 0.6


@dataclass(frozen=True)
class ReconciliationResult:
    matched: list[tuple[str, str, float]]  # (manual_topic, moodle_topic, similarity)
    unmatched_manual: list[str]
    new_moodle: list[str]


async def reconcile_manual_topics(
    db: aiosqlite.Connection,
    course_id: int,
) -> ReconciliationResult:
    """Match manual topic predictions against Moodle-sourced topics using fuzzy matching."""
    manual = await _load_topics(db, course_id, manual=True)
    moodle = await _load_topics(db, course_id, manual=False)

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

    await _persist_matches(db, course_id, matched)

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
    db: aiosqlite.Connection,
    course_id: int,
    *,
    manual: bool,
) -> list[str]:
    op = "=" if manual else "!="
    cursor = await db.execute(
        f"SELECT topic FROM topic_mappings WHERE course_id = ? AND source {op} 'manual'",  # noqa: S608
        (course_id,),
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


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
    db: aiosqlite.Connection,
    course_id: int,
    matched: list[tuple[str, str, float]],
) -> None:
    for manual_topic, moodle_topic, similarity in matched:
        await db.execute(
            "INSERT OR IGNORE INTO topic_reconciliations "
            "(manual_topic, moodle_topic, course_id, similarity) "
            "VALUES (?, ?, ?, ?)",
            (manual_topic, moodle_topic, course_id, similarity),
        )
    await db.commit()
