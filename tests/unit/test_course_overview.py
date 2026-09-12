"""Tests for the course overview service — health computation, ranking, and insights."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from sophia.services.course_overview import (
    CourseSummary,
    compute_course_health,
    compute_workload_insights,
    get_course_summaries,
    health_tooltip,
    rank_by_urgency,
)

from .._sql import exec_sql

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_COURSE_ID = 7


async def _insert_deadline(db: AsyncSession, deadline_id: str, due_at: datetime) -> None:
    await exec_sql(
        db,
        "INSERT INTO deadline_cache (id, name, course_id, course_name, deadline_type, due_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (deadline_id, deadline_id, _COURSE_ID, "Analysis 1", "assignment", due_at.isoformat()),
    )


async def _insert_rating(db: AsyncSession, topic: str, *, predicted: float, actual: float) -> None:
    await exec_sql(
        db,
        "INSERT INTO confidence_ratings (topic, course_id, predicted, actual) VALUES (?, ?, ?, ?)",
        (topic, _COURSE_ID, predicted, actual),
    )


async def _insert_topic(db: AsyncSession, topic: str) -> None:
    await exec_sql(
        db,
        "INSERT INTO topic_mappings (topic, course_id) VALUES (?, ?)",
        (topic, _COURSE_ID),
    )


async def _insert_session(db: AsyncSession, *, started: datetime, hours: float | None) -> None:
    completed = None if hours is None else started + timedelta(hours=hours)
    await exec_sql(
        db,
        "INSERT INTO study_sessions (course_id, topic, started_at, completed_at)"
        " VALUES (?, ?, ?, ?)",
        (_COURSE_ID, "Limits", started, completed),
    )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def _make_summary(**overrides: object) -> CourseSummary:
    defaults: dict[str, object] = {
        "course_id": 1,
        "course_name": "Test Course",
        "upcoming_count": 0,
        "overdue_count": 0,
        "blind_spot_count": 0,
        "avg_calibration_error": None,
        "hours_this_week": 0.0,
        "topics_total": 0,
        "topics_rated": 0,
        "days_until_nearest": None,
        "health": "green",
    }
    defaults.update(overrides)
    return CourseSummary(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# compute_course_health
# ---------------------------------------------------------------------------


class TestComputeCourseHealth:
    def test_green_no_issues(self) -> None:
        assert compute_course_health(0, 0, 14, 5.0) == "green"

    def test_yellow_single_overdue(self) -> None:
        assert compute_course_health(1, 0, 14, 5.0) == "yellow"

    def test_red_overdue_and_blind_spots(self) -> None:
        assert compute_course_health(2, 5, 1, 0.0) == "red"

    def test_low_engagement_alone_not_enough_for_yellow(self) -> None:
        assert compute_course_health(0, 0, 4, 0.5) == "green"

    def test_low_engagement_plus_blind_spots_yellow(self) -> None:
        assert compute_course_health(0, 4, 4, 1.0) == "yellow"

    def test_near_deadline_adds_score(self) -> None:
        assert compute_course_health(0, 0, 2, 5.0) == "yellow"

    def test_none_nearest_deadline(self) -> None:
        assert compute_course_health(0, 0, None, 5.0) == "green"

    @pytest.mark.parametrize(
        ("overdue", "blind", "days", "hours", "expected"),
        [
            (0, 0, 30, 10.0, "green"),
            (0, 4, 30, 10.0, "yellow"),
            (3, 0, 30, 10.0, "red"),
            (0, 0, 1, 0.0, "yellow"),
        ],
    )
    def test_parametrized_combos(
        self,
        overdue: int,
        blind: int,
        days: int | None,
        hours: float,
        expected: str,
    ) -> None:
        assert compute_course_health(overdue, blind, days, hours) == expected


# ---------------------------------------------------------------------------
# health_tooltip
# ---------------------------------------------------------------------------


class TestHealthTooltip:
    def test_on_track(self) -> None:
        s = _make_summary(overdue_count=0, blind_spot_count=0)
        assert health_tooltip(s) == "On track"

    def test_overdue_only(self) -> None:
        s = _make_summary(overdue_count=3, blind_spot_count=0)
        tip = health_tooltip(s)
        assert "3 overdue deadlines" in tip
        assert "need attention" in tip

    def test_blind_spots_only(self) -> None:
        s = _make_summary(overdue_count=0, blind_spot_count=5)
        tip = health_tooltip(s)
        assert "5 blind spots" in tip

    def test_overdue_singular(self) -> None:
        s = _make_summary(overdue_count=1, blind_spot_count=0)
        tip = health_tooltip(s)
        assert "1 overdue deadline" in tip
        assert "deadlines" not in tip

    def test_combined(self) -> None:
        s = _make_summary(overdue_count=2, blind_spot_count=4)
        tip = health_tooltip(s)
        assert "2 overdue" in tip
        assert "4 blind spot" in tip


# ---------------------------------------------------------------------------
# rank_by_urgency
# ---------------------------------------------------------------------------


class TestRankByUrgency:
    def test_red_before_green(self) -> None:
        red = _make_summary(health="red", course_name="A")
        green = _make_summary(health="green", course_name="B")
        ranked = rank_by_urgency([green, red])
        assert ranked[0].health == "red"

    def test_yellow_between_red_and_green(self) -> None:
        red = _make_summary(health="red", course_name="A")
        yellow = _make_summary(health="yellow", course_name="B")
        green = _make_summary(health="green", course_name="C")
        ranked = rank_by_urgency([green, red, yellow])
        assert [s.health for s in ranked] == ["red", "yellow", "green"]

    def test_same_health_sorted_by_issue_count(self) -> None:
        more = _make_summary(health="yellow", overdue_count=3, blind_spot_count=2, course_name="A")
        less = _make_summary(health="yellow", overdue_count=1, blind_spot_count=0, course_name="B")
        ranked = rank_by_urgency([less, more])
        assert ranked[0].course_name == "A"

    def test_empty_list(self) -> None:
        assert rank_by_urgency([]) == []


# ---------------------------------------------------------------------------
# compute_workload_insights
# ---------------------------------------------------------------------------


class TestWorkloadInsights:
    def test_imbalance_detected(self) -> None:
        s1 = _make_summary(course_name="Analysis 1", hours_this_week=20.0)
        s2 = _make_summary(course_name="Algebra", hours_this_week=2.0)
        insights = compute_workload_insights([s1, s2])
        assert any("10x" in i for i in insights)

    def test_no_imbalance_when_similar(self) -> None:
        s1 = _make_summary(course_name="Analysis 1", hours_this_week=5.0)
        s2 = _make_summary(course_name="Algebra", hours_this_week=4.0)
        insights = compute_workload_insights([s1, s2])
        assert not any("rebalancing" in i.lower() for i in insights)

    def test_blind_spot_concentration(self) -> None:
        s1 = _make_summary(course_name="Analysis 1", blind_spot_count=8)
        s2 = _make_summary(course_name="SE 2", blind_spot_count=0)
        insights = compute_workload_insights([s1, s2])
        assert any("Analysis 1" in i and "calibration" in i for i in insights)

    def test_no_insights_when_no_issues(self) -> None:
        s1 = _make_summary(course_name="A", hours_this_week=0.0, blind_spot_count=0)
        insights = compute_workload_insights([s1])
        assert insights == []

    def test_single_course_no_imbalance(self) -> None:
        s1 = _make_summary(course_name="A", hours_this_week=20.0)
        insights = compute_workload_insights([s1])
        assert not any("rebalancing" in i.lower() for i in insights)


# ---------------------------------------------------------------------------
# get_course_summaries — against a real database
# ---------------------------------------------------------------------------


@pytest.mark.postgres
class TestGetCourseSummaries:
    """The aggregation had never been executed, only mocked.

    The NiceGUI course selector patched ``get_course_summaries`` wholesale, so
    the five queries below it were typechecked and never run. Promoting the
    module out of the GUI tree in #102 is the moment to find out whether they
    still compile against the schema — `deadline_cache.due_at` is text and
    `study_sessions.started_at` is a timestamp, and the function compares one
    to an ISO string and subtracts the other.
    """

    async def test_no_deadlines_means_no_courses(self, db: AsyncSession) -> None:
        assert await get_course_summaries(db) == []

    async def test_aggregates_one_course_across_all_five_queries(
        self,
        db: AsyncSession,
    ) -> None:
        now = datetime.now(UTC)
        await _insert_deadline(db, "past", now - timedelta(days=3))
        await _insert_deadline(db, "soon", now + timedelta(days=1))
        await _insert_deadline(db, "later", now + timedelta(days=9))
        # predicted well above actual: a blind spot by the 0.2 threshold.
        await _insert_rating(db, "Limits", predicted=0.9, actual=0.4)
        await _insert_rating(db, "Series", predicted=0.5, actual=0.5)
        await _insert_topic(db, "Limits")
        await _insert_topic(db, "Series")
        await _insert_topic(db, "Continuity")
        await _insert_session(db, started=now - timedelta(days=1, hours=2), hours=2.0)

        summaries = await get_course_summaries(db)

        assert len(summaries) == 1
        summary = summaries[0]
        assert (summary.course_id, summary.course_name) == (_COURSE_ID, "Analysis 1")
        assert (summary.upcoming_count, summary.overdue_count) == (2, 1)
        assert summary.days_until_nearest == 0  # 1 day out, truncated by `.days`
        assert summary.blind_spot_count == 1
        assert summary.avg_calibration_error == pytest.approx(0.25)
        assert (summary.topics_total, summary.topics_rated) == (3, 2)
        assert summary.hours_this_week == pytest.approx(2.0)
        assert summary.health == "red"

    async def test_a_session_older_than_a_week_is_not_this_week(
        self,
        db: AsyncSession,
    ) -> None:
        now = datetime.now(UTC)
        await _insert_deadline(db, "soon", now + timedelta(days=5))
        await _insert_session(db, started=now - timedelta(days=9), hours=6.0)

        summaries = await get_course_summaries(db)

        assert summaries[0].hours_this_week == 0.0

    async def test_an_unfinished_session_contributes_no_hours(
        self,
        db: AsyncSession,
    ) -> None:
        now = datetime.now(UTC)
        await _insert_deadline(db, "soon", now + timedelta(days=5))
        await _insert_session(db, started=now - timedelta(hours=3), hours=None)

        summaries = await get_course_summaries(db)

        assert summaries[0].hours_this_week == 0.0
