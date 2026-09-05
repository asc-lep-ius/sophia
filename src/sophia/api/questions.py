"""Domain-to-transport mapping for generated questions.

Shared by the routes that serve questions — generation returns a fresh batch,
the session route reads one back — so both project the same question the same
way, engagement policy included. Kept out of ``schemas`` for the same reason
``provenance`` is: the transport package stays free of domain imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sophia.api.provenance import api_provenance
from sophia.api.schemas.content import ContentLanguage
from sophia.api.schemas.engagement import ElaborationPolicy, LearningEventType
from sophia.api.schemas.questions import OpenResponseQuestion, Question, QuestionDifficulty
from sophia.domain.errors import AthenaError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sophia.domain.learning import ContentProvenance, GeneratedQuestion
    from sophia.domain.learning import ElaborationPolicy as DomainElaborationPolicy


def question_response(
    question: GeneratedQuestion,
    provenance: ContentProvenance,
) -> Question:
    """Project a persisted question onto the published contract."""
    return OpenResponseQuestion(
        id=question.id,
        topic=question.topic,
        difficulty=QuestionDifficulty(question.difficulty),
        content_language=ContentLanguage(question.content_language.value),
        provenance=api_provenance(provenance),
        prompt=question.prompt,
        engagement_policy=policy_response(question.elaboration_policy),
    )


def require_provenance(
    provenance: Mapping[str, ContentProvenance],
    question: GeneratedQuestion,
) -> ContentProvenance:
    """Refuse to serve generated content whose provenance failed to persist.

    Silently dropping the question would hand the client a short list it cannot
    distinguish from a small one, and serving it without provenance would defeat
    the point of recording provenance at all.
    """
    record = provenance.get(question.id)
    if record is None:
        msg = f"generated question {question.id} has no provenance record"
        raise AthenaError(msg)
    return record


def policy_response(policy: DomainElaborationPolicy | None) -> ElaborationPolicy:
    """Project a stored policy, or an ungated one for a question that carries none."""
    if policy is None:
        return ElaborationPolicy(
            required_event_types=[],
            min_elaboration_chars=0,
            min_prompt_dwell_ms=0,
        )
    return ElaborationPolicy(
        required_event_types=[
            LearningEventType(event_type.value) for event_type in policy.required_event_types
        ],
        min_elaboration_chars=policy.min_elaboration_chars,
        min_prompt_dwell_ms=policy.min_prompt_dwell_ms,
    )
