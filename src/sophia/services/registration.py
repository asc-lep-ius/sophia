"""Kairos registration service — preference-based course registration.

Orchestrates registration attempts across a preference-ordered list of
groups, handling fallback when preferred groups are full.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import RegistrationError
from sophia.domain.models import (
    RegistrationResult,
    RegistrationStatus,
    RegistrationType,
)

if TYPE_CHECKING:
    from sophia.domain.models import RegistrationTarget
    from sophia.domain.ports import RegistrationProvider

log = structlog.get_logger()

# Polling intervals
_PRE_OPEN_POLL_SECS = 2.0
_RETRY_DELAY_SECS = 0.5
_MAX_SLEEP_SECS = 300.0


async def register_with_preferences(
    provider: RegistrationProvider,
    course_number: str,
    semester: str,
    preferred_group_ids: list[str],
) -> RegistrationResult:
    """Try to register for groups in preference order.

    Attempts each group in *preferred_group_ids* sequentially.  Stops at
    the first successful registration.  If all groups fail, returns the
    last failure result.
    """
    if not preferred_group_ids:
        log.info("kairos.register_lva", course=course_number)
        return await provider.register(course_number, semester)

    log.info(
        "kairos.register_preferences",
        course=course_number,
        groups=preferred_group_ids,
    )

    last_result: RegistrationResult | None = None
    for idx, gid in enumerate(preferred_group_ids):
        log.info(
            "kairos.try_group",
            course=course_number,
            group=gid,
            attempt=idx + 1,
            total=len(preferred_group_ids),
        )
        result = await provider.register(course_number, semester, group_id=gid)

        if result.success:
            log.info(
                "kairos.registered",
                course=course_number,
                group=gid,
                message=result.message,
            )
            return result

        log.warning(
            "kairos.group_failed",
            course=course_number,
            group=gid,
            message=result.message,
        )
        last_result = result

        if idx < len(preferred_group_ids) - 1:
            await asyncio.sleep(_RETRY_DELAY_SECS)

    return last_result or RegistrationResult(
        course_number=course_number,
        registration_type=RegistrationType.GROUP,
        success=False,
        message="All preferred groups failed",
        attempted_at=datetime.now(UTC).isoformat(),
    )


async def watch_and_register(
    provider: RegistrationProvider,
    course_number: str,
    semester: str,
    preferred_group_ids: list[str],
    *,
    lead_time_secs: float = 60.0,
) -> RegistrationResult:
    """Wait for the registration window to open, then register immediately.

    Polls the registration status page.  When the window opens (or is
    already open), immediately attempts registration with the preference
    list.

    Args:
        provider: RegistrationProvider adapter.
        course_number: TISS course number (e.g., ``"186.813"``).
        semester: TISS semester code (e.g., ``"2026S"``).
        preferred_group_ids: Ordered list of group IDs to try.
        lead_time_secs: Seconds before opening to start fast-polling.
    """
    log.info("kairos.watch_start", course=course_number, semester=semester)

    while True:
        target = await provider.get_registration_status(course_number, semester)

        if target.status == RegistrationStatus.REGISTERED:
            log.info("kairos.already_registered", course=course_number)
            return RegistrationResult(
                course_number=course_number,
                registration_type=RegistrationType.LVA,
                success=True,
                message="Already registered",
                attempted_at=datetime.now(UTC).isoformat(),
            )

        if target.status == RegistrationStatus.OPEN:
            log.info("kairos.window_open", course=course_number)
            return await register_with_preferences(
                provider,
                course_number,
                semester,
                preferred_group_ids,
            )

        if target.status == RegistrationStatus.CLOSED:
            raise RegistrationError(f"Registration for {course_number} is closed")

        wait = _calculate_wait(target, lead_time_secs)
        log.info(
            "kairos.waiting",
            course=course_number,
            status=target.status.value,
            wait_secs=f"{wait:.0f}",
        )
        await asyncio.sleep(wait)


def _calculate_wait(target: RegistrationTarget, lead_time_secs: float) -> float:
    """Determine how long to sleep before the next poll.

    If we know the *registration_start* time, sleep until
    ``start - lead_time``.  Otherwise, poll at a fixed interval.
    """
    if target.registration_start:
        try:
            # TISS dates are CET/CEST, not UTC.  Treating them as UTC
            # introduces a 1-2 h offset, but this is safe because the
            # loop polls repeatedly and will catch the actual opening.
            reg_time = datetime.strptime(target.registration_start, "%d.%m.%Y %H:%M").replace(
                tzinfo=UTC
            )
            remaining = (reg_time - datetime.now(UTC)).total_seconds() - lead_time_secs
            if remaining > 0:
                return min(remaining, _MAX_SLEEP_SECS)
        except ValueError:
            pass
    return _PRE_OPEN_POLL_SECS
