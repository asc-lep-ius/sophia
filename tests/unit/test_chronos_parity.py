"""The legacy due-date phrasing, kept as a record after the page that spoke it.

Issue #101 asked that Chronos "behaviour matches the legacy service" for dates,
statuses and empty states, and pinned that with a fixture both suites read:
``frontend/tests/unit/chronos-dates.test.ts`` runs the cases through the
migrated surface's ``dueDistance``, and this module used to run the same cases
through ``sophia.gui.pages.chronos.format_due_date``.

Issue #102 deleted that function with the rest of the NiceGUI tree, so the
sentence it produced now exists only as the fixture's ``legacy`` column. This
module is what keeps that column honest. It carries the legacy rule as its own
reference implementation — fifteen lines, reproduced verbatim from the page at
the commit before the deletion — and checks the recorded phrasing against it.
Not to protect an implementation nothing calls, but so that an edit to the
fixture that quietly changes what the legacy service *said* fails here instead
of rewriting history.

The day count is the part the migrated surface still consumes, and it is the
reason the fixture is expressed in elapsed seconds rather than calendar dates:
both implementations floor the seconds between two instants, which is the only
arithmetic that gives one answer in every timezone and across a daylight-saving
boundary.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "frontend" / "tests" / "fixtures" / "chronos-date-parity.json"
FRONTEND_SUITE = REPO_ROOT / "frontend" / "tests" / "unit" / "chronos-dates.test.ts"

_SECONDS_PER_DAY = 86400


def legacy_due_phrase(days: int) -> str:
    """The sentence ``format_due_date`` built from a floored day count.

    Reproduced from ``sophia/gui/pages/chronos.py`` as it stood at 22e7b71, the
    commit before issue #102 deleted it. Takes the day count rather than the
    two instants because the flooring is asserted separately below, and a
    reference implementation that repeated it could agree with the fixture by
    making the same mistake twice.
    """
    if days > 1:
        return f"in {days} days"
    if days == 1:
        return "in 1 day"
    if days == 0:
        return "today"
    abs_days = abs(days)
    if abs_days == 1:
        return "overdue by 1 day"
    return f"overdue by {abs_days} days"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _cases() -> Iterator[tuple[str, int, int, str]]:
    fixture = _fixture()
    for case in fixture["cases"]:  # type: ignore[index]
        yield (
            case["why"],
            case["offset_seconds"],
            case["days"],
            case["legacy"],
        )


def test_the_shared_fixture_is_where_both_suites_look() -> None:
    """A renamed or moved fixture fails here rather than silently halving the parity."""
    assert FIXTURE.is_file(), FIXTURE
    assert FRONTEND_SUITE.is_file(), FRONTEND_SUITE
    assert FIXTURE.name in FRONTEND_SUITE.read_text(encoding="utf-8")


@pytest.mark.parametrize(("why", "offset_seconds", "days", "legacy"), list(_cases()))
def test_legacy_day_count_matches_the_shared_fixture(
    why: str,
    offset_seconds: int,
    days: int,
    legacy: str,
) -> None:
    """The day count itself, which is what the migrated surface renders from.

    Floor division, not rounding: a deadline six hours in the past is a whole
    day overdue, and a surface that rounded would call it "today".
    """
    assert int(timedelta(seconds=offset_seconds).total_seconds() // _SECONDS_PER_DAY) == days, why


@pytest.mark.parametrize(("why", "offset_seconds", "days", "legacy"), list(_cases()))
def test_recorded_phrasing_is_what_the_legacy_rule_produced(
    why: str,
    offset_seconds: int,
    days: int,
    legacy: str,
) -> None:
    assert legacy_due_phrase(days) == legacy, why


def test_the_record_still_covers_every_branch_of_the_legacy_rule() -> None:
    """A fixture trimmed to the easy cases would pass everything above.

    Five sentences were reachable — future plural, future singular, today, and
    the two overdue forms — and a record that lost one of them would not say
    what the phrasing was any more.
    """
    recorded = {legacy for _why, _offset, _days, legacy in _cases()}

    assert {legacy_due_phrase(days) for days in (-2, -1, 0, 1, 2)} <= recorded
