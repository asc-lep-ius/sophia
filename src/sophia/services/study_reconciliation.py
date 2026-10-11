"""Reconciling a prediction with its result, once the numbers are open (#167).

Predict-observe-explain puts the explanation after the observation, and only
when the two disagree (White & Gunstone 1992). The reflection the study surface
asks for before the results is the pause; this is what follows them: the
learner says what explains the gap, and the next session on the topic shows it
back before they predict again.

Not to be confused with ``athena_reconciliation``, which matches manual topics
to TUWEL ones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sophia.domain.errors import EngagementPolicyUnmet
from sophia.domain.models import CalibrationBand, StudyReconciliation
from sophia.infra.schema import study_reconciliations, study_sessions
from sophia.services.athena_session import summarize_study_session
from sophia.services.idempotency import insert_or_fetch_row

if TYPE_CHECKING:
    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession


async def save_reconciliation(
    session: AsyncSession,
    session_id: int,
    course_id: int,
    user_id: str,
    reconciliation_text: str,
    *,
    request_id: str,
) -> tuple[StudyReconciliation, bool]:
    """Idempotently record what the learner says explains the gap.

    The prediction, score and band stored with it are the server's own, read
    at the moment it is written, so the row says what it answered even after a
    later attempt moves the score. A session with nothing to compare — no
    prediction, or nothing graded yet — has no gap to explain and is refused.
    Returns ``(reconciliation, is_new)``.
    """
    summary = await summarize_study_session(session, session_id, user_id=user_id)
    if summary is None or summary.predicted is None or summary.measured is None:
        msg = "nothing to reconcile before a prediction and a score exist"
        raise EngagementPolicyUnmet(msg, {"required": "calibration"})

    row, is_new = await insert_or_fetch_row(
        session,
        study_reconciliations,
        {
            "session_id": session_id,
            "course_id": course_id,
            "user_id": user_id,
            "predicted": summary.predicted,
            "measured": summary.measured,
            "band": summary.band.value,
            "reconciliation_text": reconciliation_text,
            "created_at": datetime.now(UTC),
            "request_id": request_id,
        },
        conflict_columns=(
            study_reconciliations.c.org_id,
            study_reconciliations.c.session_id,
            study_reconciliations.c.user_id,
            study_reconciliations.c.request_id,
        ),
        session_id=session_id,
        user_id=user_id,
        request_id=request_id,
    )
    return _row_to_reconciliation(row), is_new


async def session_reconciliation(
    session: AsyncSession,
    session_id: int,
    *,
    user_id: str,
) -> StudyReconciliation | None:
    """The learner's latest reconciliation in this session, if they wrote one."""
    row = (
        await session.execute(
            select(study_reconciliations)
            .where(
                study_reconciliations.c.session_id == session_id,
                study_reconciliations.c.user_id == user_id,
            )
            .order_by(study_reconciliations.c.id.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else _row_to_reconciliation(row)


async def previous_reconciliation(
    session: AsyncSession,
    session_id: int,
    *,
    user_id: str,
) -> StudyReconciliation | None:
    """The learner's last reconciliation on this session's topic, from another session.

    This is what Predict shows back before the learner commits to a new
    rating. Scoped to the learner, like the prediction it answers.
    """
    current = (
        select(study_sessions.c.course_id, study_sessions.c.topic)
        .where(study_sessions.c.id == session_id)
        .subquery()
    )
    row = (
        await session.execute(
            select(study_reconciliations)
            .join(study_sessions, study_sessions.c.id == study_reconciliations.c.session_id)
            .join(
                current,
                (study_sessions.c.course_id == current.c.course_id)
                & (study_sessions.c.topic == current.c.topic),
            )
            .where(
                study_reconciliations.c.user_id == user_id,
                study_reconciliations.c.session_id != session_id,
            )
            .order_by(study_reconciliations.c.id.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else _row_to_reconciliation(row)


def _row_to_reconciliation(row: Row[tuple[object, ...]]) -> StudyReconciliation:
    return StudyReconciliation(
        id=row.id,
        session_id=row.session_id,
        course_id=row.course_id,
        user_id=row.user_id,
        predicted=row.predicted,
        measured=row.measured,
        band=CalibrationBand(row.band),
        reconciliation_text=row.reconciliation_text,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )
