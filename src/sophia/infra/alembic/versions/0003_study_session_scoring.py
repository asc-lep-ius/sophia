"""Study session scoring — attempt phase and session-scoped questions.

``question_attempts`` gains ``phase``, which is what lets the server compute a
pre→post improvement figure at all: without it every attempt in a session is
indistinguishable, so "did studying help" cannot be answered from the data.
Existing rows default to ``practice`` — they predate the distinction and must
not be counted at either end of a comparison they were never part of.

``generated_questions`` gains ``session_id`` so a session's question set can be
read back instead of regenerated on every page load. It is nullable: questions
generated outside a live study session (the CLI, a later authoring surface)
belong to no session. See issue #98.

Revision ID: 0003_study_session_scoring
Revises: 0002_study_realtime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_study_session_scoring"
down_revision: str | None = "0002_study_realtime"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "question_attempts",
        sa.Column("phase", sa.Text(), server_default="practice", nullable=False),
    )
    op.create_check_constraint(
        "phase_valid",
        "question_attempts",
        "phase IN ('pre_test', 'practice', 'post_test')",
    )

    op.add_column("generated_questions", sa.Column("session_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_generated_questions_session_id_study_sessions"),
        "generated_questions",
        "study_sessions",
        ["session_id"],
        ["id"],
    )
    op.create_index(
        "idx_generated_questions_session",
        "generated_questions",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_generated_questions_session", table_name="generated_questions")
    op.drop_constraint(
        op.f("fk_generated_questions_session_id_study_sessions"),
        "generated_questions",
        type_="foreignkey",
    )
    op.drop_column("generated_questions", "session_id")

    op.drop_constraint(op.f("ck_question_attempts_phase_valid"), "question_attempts", type_="check")
    op.drop_column("question_attempts", "phase")
