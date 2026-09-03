"""Study realtime schema — event log, idempotency keys, and grading columns.

Adds the append-only ``study_events`` log the SSE endpoint replays from, a
``study_reflections`` table (reflection text was never persisted before this),
and ``session_id``/``request_id``/``user_id`` columns on the submission tables
the study realtime endpoints write to, so a client-generated request id can be
enforced as a durable idempotency key per ``(org_id, session_id, user_id,
request_id)`` rather than an in-process map.

``question_attempts`` gains ``score``/``self_rating`` for server-side grading.
``study_sessions``/``confidence_ratings`` gain ``legacy_scored``, backfilled
``true`` for every row that already carries a score: nothing before this
revision could have produced a correctly-graded score, so every existing scored
row was written by the non-empty-answer heuristic this issue retires. See issue
#97.

Revision ID: 0002_study_realtime
Revises: 0001_baseline
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_study_realtime"
down_revision: str | None = "0001_baseline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "study_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("client_time", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "server_time",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("org_id", sa.Text(), server_default="default", nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["study_sessions.id"],
            name=op.f("fk_study_events_session_id_study_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_events")),
    )
    op.create_index("idx_study_events_retention", "study_events", ["server_time"], unique=False)
    op.create_index("idx_study_events_session", "study_events", ["session_id", "id"], unique=False)

    op.create_table(
        "study_reflections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("reflection_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("org_id", sa.Text(), server_default="default", nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["study_sessions.id"],
            name=op.f("fk_study_reflections_session_id_study_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_reflections")),
        sa.UniqueConstraint(
            "org_id",
            "session_id",
            "user_id",
            "request_id",
            name="uq_study_reflections_session_request",
        ),
    )
    op.create_index(
        "idx_study_reflections_session", "study_reflections", ["session_id"], unique=False
    )

    op.add_column("confidence_ratings", sa.Column("user_id", sa.Text(), nullable=True))
    op.add_column("confidence_ratings", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("confidence_ratings", sa.Column("request_id", sa.Text(), nullable=True))
    op.add_column(
        "confidence_ratings",
        sa.Column("legacy_scored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_unique_constraint(
        "uq_confidence_ratings_session_request",
        "confidence_ratings",
        ["org_id", "session_id", "user_id", "request_id"],
    )
    op.create_foreign_key(
        op.f("fk_confidence_ratings_session_id_study_sessions"),
        "confidence_ratings",
        "study_sessions",
        ["session_id"],
        ["id"],
    )

    op.add_column("question_attempts", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("question_attempts", sa.Column("request_id", sa.Text(), nullable=True))
    op.add_column("question_attempts", sa.Column("score", sa.Float(), nullable=True))
    op.add_column("question_attempts", sa.Column("self_rating", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "score_ratio",
        "question_attempts",
        "score IS NULL OR score BETWEEN 0.0 AND 1.0",
    )
    op.create_check_constraint(
        "self_rating_range",
        "question_attempts",
        "self_rating IS NULL OR self_rating BETWEEN 1 AND 4",
    )
    op.create_unique_constraint(
        "uq_question_attempts_session_request",
        "question_attempts",
        ["org_id", "session_id", "user_id", "request_id"],
    )
    op.create_foreign_key(
        op.f("fk_question_attempts_session_id_study_sessions"),
        "question_attempts",
        "study_sessions",
        ["session_id"],
        ["id"],
    )

    op.add_column("self_explanations", sa.Column("user_id", sa.Text(), nullable=True))
    op.add_column("self_explanations", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("self_explanations", sa.Column("request_id", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_self_explanations_session_request",
        "self_explanations",
        ["org_id", "session_id", "user_id", "request_id"],
    )
    op.create_foreign_key(
        op.f("fk_self_explanations_session_id_study_sessions"),
        "self_explanations",
        "study_sessions",
        ["session_id"],
        ["id"],
    )

    op.add_column("student_flashcards", sa.Column("user_id", sa.Text(), nullable=True))
    op.add_column("student_flashcards", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("student_flashcards", sa.Column("request_id", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_student_flashcards_session_request",
        "student_flashcards",
        ["org_id", "session_id", "user_id", "request_id"],
    )
    op.create_foreign_key(
        op.f("fk_student_flashcards_session_id_study_sessions"),
        "student_flashcards",
        "study_sessions",
        ["session_id"],
        ["id"],
    )

    op.add_column("study_sessions", sa.Column("user_id", sa.Text(), nullable=True))
    op.add_column(
        "study_sessions",
        sa.Column("legacy_scored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # Every row scored before this revision was scored by the non-empty-answer
    # heuristic — no correct grading path existed until this migration's
    # companion code lands. Mark them so calibration views can exclude them.
    op.execute("UPDATE study_sessions SET legacy_scored = true WHERE post_test_score IS NOT NULL")
    op.execute("UPDATE confidence_ratings SET legacy_scored = true WHERE actual IS NOT NULL")


def downgrade() -> None:
    op.drop_column("study_sessions", "legacy_scored")
    op.drop_column("study_sessions", "user_id")

    op.drop_constraint(
        op.f("fk_student_flashcards_session_id_study_sessions"),
        "student_flashcards",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_student_flashcards_session_request"), "student_flashcards", type_="unique"
    )
    op.drop_column("student_flashcards", "request_id")
    op.drop_column("student_flashcards", "session_id")
    op.drop_column("student_flashcards", "user_id")

    op.drop_constraint(
        op.f("fk_self_explanations_session_id_study_sessions"),
        "self_explanations",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_self_explanations_session_request"), "self_explanations", type_="unique"
    )
    op.drop_column("self_explanations", "request_id")
    op.drop_column("self_explanations", "session_id")
    op.drop_column("self_explanations", "user_id")

    op.drop_constraint(
        op.f("fk_question_attempts_session_id_study_sessions"),
        "question_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_question_attempts_session_request"), "question_attempts", type_="unique"
    )
    op.drop_constraint(
        op.f("ck_question_attempts_self_rating_range"), "question_attempts", type_="check"
    )
    op.drop_constraint(op.f("ck_question_attempts_score_ratio"), "question_attempts", type_="check")
    op.drop_column("question_attempts", "self_rating")
    op.drop_column("question_attempts", "score")
    op.drop_column("question_attempts", "request_id")
    op.drop_column("question_attempts", "session_id")

    op.drop_constraint(
        op.f("fk_confidence_ratings_session_id_study_sessions"),
        "confidence_ratings",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_confidence_ratings_session_request"), "confidence_ratings", type_="unique"
    )
    op.drop_column("confidence_ratings", "legacy_scored")
    op.drop_column("confidence_ratings", "request_id")
    op.drop_column("confidence_ratings", "session_id")
    op.drop_column("confidence_ratings", "user_id")

    op.drop_index("idx_study_reflections_session", table_name="study_reflections")
    op.drop_table("study_reflections")

    op.drop_index("idx_study_events_session", table_name="study_events")
    op.drop_index("idx_study_events_retention", table_name="study_events")
    op.drop_table("study_events")
