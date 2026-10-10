"""Processing from the browser: the job queue, the worker, and per-lecture topics.

``ingestion_jobs`` is the queue between the API and the processing worker, and
``ingestion_workers`` is where a worker says whether it can process at all, so
a press of Process on a box with no usable GPU is refused with the reason
rather than queued forever. ``topic_extractions`` records which lectures have
been through topic extraction and why one failed; ``topic_origins`` records
which lectures each topic came from, so the topic list can name them and a
second run reads only what is new. ``learning_path_settings`` gains the
course's transcription language (NULL: Whisper detects it) and whether new
recordings for the course are processed without being asked. See issue #128.

Revision ID: 0006_lecture_processing
Revises: 0005_topics_keyed_by_course
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision: str = "0006_lecture_processing"
down_revision: str | None = "0005_topics_keyed_by_course"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def _org_id() -> sa.Column[str]:
    return sa.Column("org_id", sa.Text(), nullable=False, server_default="default")


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("requested_by", sa.Text(), nullable=False, server_default="student"),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("module_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", TIMESTAMP(timezone=True), nullable=True),
        _org_id(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="status_allowed",
        ),
    )
    op.create_index("idx_ingestion_jobs_course", "ingestion_jobs", ["course_id"])
    op.create_index(
        "uq_ingestion_jobs_active_course",
        "ingestion_jobs",
        ["course_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "ingestion_workers",
        sa.Column("worker_id", sa.Text(), primary_key=True),
        sa.Column("hostname", sa.Text(), nullable=False, server_default=""),
        sa.Column("capable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("gpu_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", TIMESTAMP(timezone=True), server_default=_NOW),
        sa.Column("last_seen_at", TIMESTAMP(timezone=True), server_default=_NOW),
        _org_id(),
    )

    op.create_table(
        "topic_extractions",
        sa.Column(
            "episode_id",
            sa.Text(),
            sa.ForeignKey(
                "transcriptions.episode_id",
                name=op.f("fk_topic_extractions_episode_id_transcriptions"),
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("topic_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("extracted_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
        _org_id(),
    )
    op.create_index("idx_topic_extractions_course", "topic_extractions", ["course_id"])

    op.create_table(
        "topic_origins",
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("episode_id", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
        _org_id(),
        sa.PrimaryKeyConstraint("topic", "course_id", "episode_id", name=op.f("pk_topic_origins")),
    )
    op.create_index("idx_topic_origins_course", "topic_origins", ["course_id"])
    op.create_index("idx_topic_origins_episode", "topic_origins", ["episode_id"])

    op.add_column(
        "learning_path_settings",
        sa.Column("transcription_language", sa.Text(), nullable=True),
    )
    op.add_column(
        "learning_path_settings",
        sa.Column(
            "ingestion_subscribed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("learning_path_settings", "ingestion_subscribed")
    op.drop_column("learning_path_settings", "transcription_language")
    op.drop_index("idx_topic_origins_episode", table_name="topic_origins")
    op.drop_index("idx_topic_origins_course", table_name="topic_origins")
    op.drop_table("topic_origins")
    op.drop_index("idx_topic_extractions_course", table_name="topic_extractions")
    op.drop_table("topic_extractions")
    op.drop_table("ingestion_workers")
    op.drop_index("uq_ingestion_jobs_active_course", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_course", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
