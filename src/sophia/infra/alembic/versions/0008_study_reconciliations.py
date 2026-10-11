"""A reason with the prediction, and a reconciliation after the results.

``confidence_ratings`` gains ``reason``: the optional "because…" line a learner
can store with their rating, so the result has a stated conception to
contradict. ``study_reconciliations`` holds what a learner wrote about the gap
between their prediction and their score once the results opened. Each row
copies the prediction, score and band it answered, so it can be read later
against what it was written about. See #167.

Revision ID: 0008_study_reconciliations
Revises: 0007_lecture_recordings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision: str = "0008_study_reconciliations"
down_revision: str | None = "0007_lecture_recordings"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column("confidence_ratings", sa.Column("reason", sa.Text(), nullable=True))

    op.create_table(
        "study_reconciliations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("predicted", sa.Float(), nullable=False),
        sa.Column("measured", sa.Float(), nullable=False),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column("reconciliation_text", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW, nullable=True),
        sa.Column("org_id", sa.Text(), server_default="default", nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "predicted BETWEEN 0.0 AND 1.0",
            name=op.f("ck_study_reconciliations_predicted_ratio"),
        ),
        sa.CheckConstraint(
            "measured BETWEEN 0.0 AND 1.0",
            name=op.f("ck_study_reconciliations_measured_ratio"),
        ),
        sa.CheckConstraint(
            "band IN ('well_calibrated', 'overconfident', 'underconfident')",
            name=op.f("ck_study_reconciliations_band_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["study_sessions.id"],
            name=op.f("fk_study_reconciliations_session_id_study_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_reconciliations")),
        sa.UniqueConstraint(
            "org_id",
            "session_id",
            "user_id",
            "request_id",
            name="uq_study_reconciliations_session_request",
        ),
    )
    op.create_index(
        "idx_study_reconciliations_session",
        "study_reconciliations",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_study_reconciliations_session", table_name="study_reconciliations")
    op.drop_table("study_reconciliations")
    op.drop_column("confidence_ratings", "reason")
