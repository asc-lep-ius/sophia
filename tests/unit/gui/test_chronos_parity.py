"""The legacy due-date phrasing, held against the fixture the new surface uses.

Issue #101 asks that Chronos "behaviour matches the legacy service" for dates,
statuses and empty states. A pair of independent expectations would not show
that: each suite would be free to drift, and the drift would only surface when
a learner noticed the two apps disagreeing about when something was due.

So both read the same file. ``frontend/tests/unit/chronos-dates.test.ts`` runs
these cases through the migrated surface's ``dueDistance``; this module runs
them through the NiceGUI service that surface replaces. The fixture is
deliberately expressed in elapsed seconds rather than in calendar dates,
because that is the thing being preserved — both implementations floor the
seconds between two instants, which is the only arithmetic that gives one
answer in every timezone and across a daylight-saving boundary.

This module is *not* marked for phase 5 removal even though
``test_chronos.py`` is. The phrasing has to outlive the page it came from,
and after the NiceGUI page is deleted these cases are what says what the
phrasing was.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sophia.gui.pages.chronos import format_due_date

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "frontend" / "tests" / "fixtures" / "chronos-date-parity.json"


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


@pytest.mark.parametrize(("why", "offset_seconds", "days", "legacy"), list(_cases()))
def test_legacy_phrasing_matches_the_shared_fixture(
    why: str,
    offset_seconds: int,
    days: int,
    legacy: str,
) -> None:
    now = datetime.fromisoformat(str(_fixture()["now"]))
    due_at = now + timedelta(seconds=offset_seconds)

    assert format_due_date(due_at, now=now) == legacy, why


@pytest.mark.parametrize(("why", "offset_seconds", "days", "legacy"), list(_cases()))
def test_legacy_day_count_matches_the_shared_fixture(
    why: str,
    offset_seconds: int,
    days: int,
    legacy: str,
) -> None:
    """The day count itself, which is what the migrated surface renders from.

    The legacy service only ever exposed the finished sentence, so this
    recomputes the number the sentence was built from. Floor division, not
    rounding: a deadline six hours in the past is a whole day overdue, and a
    surface that rounded would call it "today".
    """
    assert int(timedelta(seconds=offset_seconds).total_seconds() // 86400) == days, why
