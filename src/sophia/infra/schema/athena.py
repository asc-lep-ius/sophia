"""Topic, confidence, study, flashcard, and review scheduling tables."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP

from sophia.infra.schema._shared import metadata, org_id_column, text_course_id_column

_NOW = text("CURRENT_TIMESTAMP")

topic_mappings = Table(
    "topic_mappings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("topic", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("source", Text, nullable=False, server_default="lecture"),
    Column("frequency", Integer, nullable=False, server_default=text("1")),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    CheckConstraint("source IN ('lecture', 'quiz', 'manual')", name="source_allowed"),
    UniqueConstraint("topic", "course_id", "source", name="uq_topic_mappings_topic"),
    Index("idx_topic_mappings_course", "course_id"),
)

topic_lecture_links = Table(
    "topic_lecture_links",
    metadata,
    Column("topic", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("chunk_id", Text, nullable=False),
    Column("episode_id", Text, nullable=False),
    Column("score", Float(), nullable=False, server_default=text("0.0")),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    PrimaryKeyConstraint("topic", "course_id", "chunk_id"),
    Index("idx_topic_lecture_links_course", "course_id"),
    Index("idx_topic_lecture_links_episode", "episode_id"),
)

topic_reconciliations = Table(
    "topic_reconciliations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("manual_topic", Text, nullable=False),
    Column("moodle_topic", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("similarity", Float(), nullable=False),
    Column("reconciled_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    UniqueConstraint("manual_topic", "course_id", name="uq_topic_reconciliations_manual_topic"),
)

confidence_ratings = Table(
    "confidence_ratings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("topic", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("predicted", Float(), nullable=False),
    Column("actual", Float()),
    Column("rated_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("actual_at", TIMESTAMP(timezone=True)),
    org_id_column(),
    CheckConstraint("predicted BETWEEN 0.0 AND 1.0", name="predicted_ratio"),
    CheckConstraint("actual IS NULL OR actual BETWEEN 0.0 AND 1.0", name="actual_ratio"),
    Index("idx_confidence_ratings_course", "course_id"),
    Index("idx_confidence_ratings_topic", "course_id", "topic"),
)

study_sessions = Table(
    "study_sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("course_id", Integer, nullable=False),
    Column("topic", Text, nullable=False),
    Column("pre_test_score", Float()),
    Column("post_test_score", Float()),
    Column("started_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("completed_at", TIMESTAMP(timezone=True)),
    org_id_column(),
    CheckConstraint(
        "pre_test_score IS NULL OR pre_test_score BETWEEN 0.0 AND 1.0",
        name="pre_test_ratio",
    ),
    CheckConstraint(
        "post_test_score IS NULL OR post_test_score BETWEEN 0.0 AND 1.0",
        name="post_test_ratio",
    ),
    Index("idx_study_sessions_course", "course_id"),
    Index("idx_study_sessions_topic", "course_id", "topic"),
)

student_flashcards = Table(
    "student_flashcards",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("course_id", Integer, nullable=False),
    Column("topic", Text, nullable=False),
    Column("front", Text, nullable=False),
    Column("back", Text, nullable=False),
    Column("source", Text, nullable=False, server_default="study"),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    CheckConstraint("source IN ('study', 'lecture', 'manual')", name="source_allowed"),
    Index("idx_flashcards_course", "course_id"),
    Index("idx_flashcards_topic", "course_id", "topic"),
)

card_review_attempts = Table(
    "card_review_attempts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "flashcard_id",
        Integer,
        ForeignKey("student_flashcards.id"),
        nullable=False,
    ),
    Column("success", Boolean(), nullable=False),
    Column("reviewed_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    text_course_id_column(),
    Index("idx_card_reviews_flashcard", "flashcard_id"),
)

self_explanations = Table(
    "self_explanations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "flashcard_id",
        Integer,
        ForeignKey("student_flashcards.id"),
        nullable=False,
    ),
    Column("student_explanation", Text, nullable=False),
    Column("scaffold_level", Integer, nullable=False, server_default=text("3")),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    text_course_id_column(),
    CheckConstraint("scaffold_level BETWEEN 0 AND 3", name="scaffold_level_range"),
    Index("idx_self_explanations_flashcard", "flashcard_id"),
)

review_schedule = Table(
    "review_schedule",
    metadata,
    Column("topic", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("interval_index", Integer, nullable=False, server_default=text("0")),
    Column("last_reviewed_at", TIMESTAMP(timezone=True)),
    Column("next_review_at", TIMESTAMP(timezone=True), nullable=False),
    Column("score_at_last_review", Float()),
    Column("difficulty", Float(), server_default=text("0.3")),
    Column("stability", Float(), server_default=text("1.0")),
    Column("review_count", Integer, server_default=text("0")),
    org_id_column(),
    PrimaryKeyConstraint("topic", "course_id"),
    Index("idx_review_schedule_due", "next_review_at"),
)
