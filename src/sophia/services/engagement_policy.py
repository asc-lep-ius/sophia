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

    from sophia.domain.learning import ElaborationPolicy, EventPayloadValue, LearningEvent

ELABORATION_LENGTH_KEY = "text_length"
DWELL_KEY = "dwell_ms"


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """Whether a policy is satisfied, and what is missing when it is not."""

    met: bool
    missing_event_types: tuple[LearningEventType, ...] = ()
    elaboration_chars: int = 0
    prompt_dwell_ms: int = 0

    @property
    def params(self) -> dict[str, str | int]:
        """Machine-readable reason, carried in the 412 error detail."""
        return {
            "missing_event_types": ",".join(
                event_type.value for event_type in self.missing_event_types
            ),
            "elaboration_chars": self.elaboration_chars,
            "prompt_dwell_ms": self.prompt_dwell_ms,
        }


def evaluate_elaboration_policy(
    policy: ElaborationPolicy,
    events: Sequence[LearningEvent],
) -> PolicyOutcome:
    """Check a learner's trace for one question against an elaboration policy."""
    recorded_types = {event.event_type for event in events}
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

    met = (
        not missing
        and elaboration_chars >= policy.min_elaboration_chars
        and prompt_dwell_ms >= policy.min_prompt_dwell_ms
    )
    return PolicyOutcome(
        met=met,
        missing_event_types=missing,
        elaboration_chars=elaboration_chars,
        prompt_dwell_ms=prompt_dwell_ms,
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
