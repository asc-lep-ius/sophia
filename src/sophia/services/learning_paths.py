"""The learning paths a learner can study, and the one login may select for them.

A learning path is a TUWEL course: there is no courses table, so the list is the
learner's current enrolments, read live. It comes from the container's TUWEL
session, the box's own, exactly as the quickstart overview and the deadline sync
read enrolments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sophia.domain.models import Course
    from sophia.infra.di import AppContainer


async def list_learning_paths(app: AppContainer) -> list[Course]:
    """The learner's current enrolments, one learning path each."""
    return await app.moodle.get_enrolled_courses()


def default_learning_path(learning_paths: Sequence[Course]) -> Course | None:
    """The learning path a login selects unasked: the only one, or none.

    A single enrolment has one possible answer, so asking would only be a click.
    With several there is no right guess, and nothing remembers a previous
    choice across logins, so the learner picks.
    """
    if len(learning_paths) != 1:
        return None
    return learning_paths[0]
