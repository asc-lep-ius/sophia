"""Postgres schema metadata — the single source Alembic autogenerates against.

Import every table module here so that ``metadata`` is complete the moment this
package is imported. A table that is defined but never imported is invisible to
autogenerate, which shows up as a silent DROP TABLE in the next revision.
"""

from sophia.infra.schema._shared import DEFAULT_SCOPE, NAMING_CONVENTION, metadata
from sophia.infra.schema.athena import (
    card_review_attempts,
    confidence_ratings,
    module_course_rekeys,
    review_schedule,
    self_explanations,
    student_flashcards,
    study_reconciliations,
    study_reflections,
    study_sessions,
    topic_extractions,
    topic_lecture_links,
    topic_mappings,
    topic_origins,
    topic_reconciliations,
)
from sophia.infra.schema.chronos import (
    active_timers,
    deadline_cache,
    deadline_reflections,
    effort_estimates,
    time_entries,
)
from sophia.infra.schema.core import (
    book_cache,
    discovered_references,
    downloads,
    metacognition_log,
    scheduled_jobs,
)
from sophia.infra.schema.hermes import (
    course_materials,
    ingestion_jobs,
    ingestion_workers,
    knowledge_index,
    lecture_downloads,
    lecture_modules,
    lecture_recordings,
    transcript_segments,
    transcriptions,
)
from sophia.infra.schema.learning import (
    content_provenance,
    content_source_spans,
    content_translations,
    generated_questions,
    learning_events,
    learning_path_settings,
    question_attempts,
    study_events,
)

__all__ = [
    "DEFAULT_SCOPE",
    "NAMING_CONVENTION",
    "active_timers",
    "book_cache",
    "card_review_attempts",
    "confidence_ratings",
    "content_provenance",
    "content_source_spans",
    "content_translations",
    "course_materials",
    "deadline_cache",
    "deadline_reflections",
    "discovered_references",
    "downloads",
    "effort_estimates",
    "generated_questions",
    "ingestion_jobs",
    "ingestion_workers",
    "knowledge_index",
    "learning_events",
    "learning_path_settings",
    "lecture_downloads",
    "lecture_modules",
    "lecture_recordings",
    "metacognition_log",
    "metadata",
    "module_course_rekeys",
    "question_attempts",
    "review_schedule",
    "scheduled_jobs",
    "self_explanations",
    "student_flashcards",
    "study_events",
    "study_reconciliations",
    "study_reflections",
    "study_sessions",
    "time_entries",
    "topic_extractions",
    "topic_lecture_links",
    "topic_mappings",
    "topic_origins",
    "topic_reconciliations",
    "transcript_segments",
    "transcriptions",
]
