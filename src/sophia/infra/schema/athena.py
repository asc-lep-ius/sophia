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

# One row per lecture whose transcript went through topic extraction, so a
# course can be processed again without re-reading the lectures it already has
# topics for, and a lecture whose extraction failed keeps its reason and is
# retried next time (#128).
topic_extractions = Table(
    "topic_extractions",
    metadata,
    Column(
        "episode_id",
        Text,
        ForeignKey("transcriptions.episode_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("course_id", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("topic_count", Integer, nullable=False, server_default=text("0")),
    Column("error", Text),
    Column("extracted_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    Index("idx_topic_extractions_course", "course_id"),
)

# Which lectures a topic was extracted from. A topic stays one row in
# ``topic_mappings`` however many lectures mention it, because ratings and
# reviews are keyed by that one (topic, course) pair; this is what lets the
# topic list say which lecture each one came from (#128).
topic_origins = Table(
    "topic_origins",
    metadata,
    Column("topic", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("episode_id", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    PrimaryKeyConstraint("topic", "course_id", "episode_id"),
    Index("idx_topic_origins_course", "course_id"),
    Index("idx_topic_origins_episode", "episode_id"),
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
    Column("user_id", Text),
    Column("session_id", Integer, ForeignKey("study_sessions.id")),
    Column("request_id", Text),
    Column("legacy_scored", Boolean(), nullable=False, server_default=text("false")),
    # The learner's optional "because…" line, the conception a result can contradict.
    Column("reason", Text),
    CheckConstraint("predicted BETWEEN 0.0 AND 1.0", name="predicted_ratio"),
    CheckConstraint("actual IS NULL OR actual BETWEEN 0.0 AND 1.0", name="actual_ratio"),
    UniqueConstraint(
        "org_id",
        "session_id",
        "user_id",
        "request_id",
        name="uq_confidence_ratings_session_request",
    ),
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
    Column("user_id", Text),
    Column("legacy_scored", Boolean(), nullable=False, server_default=text("false")),
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
    Column("user_id", Text),
    Column("session_id", Integer, ForeignKey("study_sessions.id")),
    Column("request_id", Text),
    CheckConstraint("source IN ('study', 'lecture', 'manual')", name="source_allowed"),
    UniqueConstraint(
        "org_id",
        "session_id",
        "user_id",
        "request_id",
        name="uq_student_flashcards_session_request",
    ),
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
    Column("user_id", Text),
    Column("session_id", Integer, ForeignKey("study_sessions.id")),
    Column("request_id", Text),
    CheckConstraint("scaffold_level BETWEEN 0 AND 3", name="scaffold_level_range"),
    UniqueConstraint(
        "org_id",
        "session_id",
        "user_id",
        "request_id",
        name="uq_self_explanations_session_request",
    ),
    Index("idx_self_explanations_flashcard", "flashcard_id"),
)

study_reflections = Table(
    "study_reflections",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", Integer, ForeignKey("study_sessions.id"), nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("prompt", Text, nullable=False),
    Column("reflection_text", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    Column("request_id", Text),
    UniqueConstraint(
        "org_id",
        "session_id",
        "user_id",
        "request_id",
        name="uq_study_reflections_session_request",
    ),
    Index("idx_study_reflections_session", "session_id"),
)

# What a learner wrote, once the results opened, about the gap between their
# prediction and their score (#167). Not to be confused with
# topic_reconciliations, which matches manual topics to TUWEL ones. The
# prediction, score and band are copied in at the moment it was written, so it
# can later be read against what it answered rather than a score that moved.
study_reconciliations = Table(
    "study_reconciliations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", Integer, ForeignKey("study_sessions.id"), nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("predicted", Float(), nullable=False),
    Column("measured", Float(), nullable=False),
    Column("band", Text, nullable=False),
    Column("reconciliation_text", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    Column("request_id", Text, nullable=False),
    CheckConstraint("predicted BETWEEN 0.0 AND 1.0", name="predicted_ratio"),
    CheckConstraint("measured BETWEEN 0.0 AND 1.0", name="measured_ratio"),
    CheckConstraint(
        "band IN ('well_calibrated', 'overconfident', 'underconfident')",
        name="band_allowed",
    ),
    UniqueConstraint(
        "org_id",
        "session_id",
        "user_id",
        "request_id",
        name="uq_study_reconciliations_session_request",
    ),
    Index("idx_study_reconciliations_session", "session_id"),
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

# Each topic, rating and review row migration 0005 moved from an Opencast module
# id to the course that owns the module, and where it came from. Only the
# downgrade reads it: without it, rows from two modules of one course would be
# indistinguishable once re-keyed, and could not be split back (#127).
module_course_rekeys = Table(
    "module_course_rekeys",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("table_name", Text, nullable=False),
    # How the moved row is found again: its id where the table has one,
    # otherwise its key columns besides course_id.
    Column("row_id", Integer),
    Column("topic", Text),
    Column("chunk_id", Text),
    Column("module_id", Integer, nullable=False),
    Column("course_id", Integer, nullable=False),
    org_id_column(),
)
