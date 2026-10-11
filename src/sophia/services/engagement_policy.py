"""Server-side engagement policy: did the learner actually do the work?

The policy is evaluated against ingested ``LearningEvent`` rows rather than
against anything the answering client asserts. A client that wants to bypass it
has to fabricate its own process trace and leave that fabrication in the audit
log, which is what makes anti-cheating triage possible at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sophia.domain.learning import LearningEventType

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sophia.domain.learning import ElaborationPolicy, EventPayloadValue, LearningEvent

ELABORATION_LENGTH_KEY = "text_length"
DWELL_KEY = "dwell_ms"

SESSION_SCOPED_EVENT_TYPES = frozenset({LearningEventType.PREDICTION_MADE})
"""Required once per study session rather than once per question.

The confidence prediction is committed once, on the predict route against the
session's anchor question, and covers every card the session goes on to work.
It is still required: a session in which nothing was predicted unlocks nothing.
"""


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """Whether a policy is satisfied, and what is missing when it is not."""

    met: bool
    missing_event_types: tuple[LearningEventType, ...] = ()
    elaboration_chars: int = 0
    prompt_dwell_ms: int = 0
    revealed_before_prediction: bool = False

    @property
    def params(self) -> dict[str, str | int]:
        """Machine-readable reason, carried in the 412 error detail."""
        return {
            "missing_event_types": ",".join(
                event_type.value for event_type in self.missing_event_types
            ),
            "elaboration_chars": self.elaboration_chars,
            "prompt_dwell_ms": self.prompt_dwell_ms,
            "revealed_before_prediction": self.revealed_before_prediction,
        }


def evaluate_elaboration_policy(
    policy: ElaborationPolicy,
    events: Sequence[LearningEvent],
    session_events: Sequence[LearningEvent] = (),
    *,
    session_id: int | None = None,
) -> PolicyOutcome:
    """Check a learner's trace for one question against an elaboration policy.

    ``events`` is the trace for the question itself. ``session_events`` is the
    trace for the study session the attempt belongs to, and counts only towards
    the session-scoped requirements. ``session_id`` names that session, so a
    reveal of the same question in another session is not held against this one.
    """
    recorded_types = {event.event_type for event in events} | {
        event.event_type
        for event in session_events
        if event.event_type in SESSION_SCOPED_EVENT_TYPES
    }
    missing = tuple(
        event_type for event_type in policy.required_event_types if event_type not in recorded_types
    )

    elaboration_chars = _max_int_payload(
        events,
        LearningEventType.ELABORATION_WRITTEN,
        ELABORATION_LENGTH_KEY,
    )
    prompt_dwell_ms = _max_int_payload(
        events,
        LearningEventType.PROMPT_SHOWN,
        DWELL_KEY,
    )

    revealed_early = _revealed_before_prediction(events, session_events, session_id)

    met = (
        not missing
        and not revealed_early
        and elaboration_chars >= policy.min_elaboration_chars
        and prompt_dwell_ms >= policy.min_prompt_dwell_ms
    )
    return PolicyOutcome(
        met=met,
        missing_event_types=missing,
        elaboration_chars=elaboration_chars,
        prompt_dwell_ms=prompt_dwell_ms,
        revealed_before_prediction=revealed_early,
    )


def _revealed_before_prediction(
    events: Sequence[LearningEvent],
    session_events: Sequence[LearningEvent],
    session_id: int | None,
) -> bool:
    """Whether the answer was on screen before the session's first prediction.

    A prediction made with the material in view is inflated in exactly the way
    the predict step exists to expose (Koriat & Bjork 2005), so it does not
    count as one. The first prediction is the one that matters: changing the
    rating after a reveal does not make the earlier reveal any less early.
    """
    first_prediction = _earliest([*events, *session_events], LearningEventType.PREDICTION_MADE)
    if first_prediction is None:
        return False
    reveals = [
        event for event in events if session_id is None or event.session_id in (None, session_id)
    ]
    first_reveal = _earliest(reveals, LearningEventType.ANSWER_REVEALED)
    return first_reveal is not None and first_reveal < first_prediction


def _earliest(events: Sequence[LearningEvent], event_type: LearningEventType) -> datetime | None:
    return min(
        (event.occurred_at for event in events if event.event_type is event_type),
        default=None,
    )


def _max_int_payload(
    events: Sequence[LearningEvent],
    event_type: LearningEventType,
    key: str,
) -> int:
    values = [_as_int(event.payload.get(key)) for event in events if event.event_type is event_type]
    return max(values, default=0)


def _as_int(value: EventPayloadValue) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0
