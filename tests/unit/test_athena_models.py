"""Tests for Athena domain models, errors, events, and ports."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sophia.domain.errors import AthenaError, SophiaError, TopicExtractionError
from sophia.domain.events import TopicLectureLinked, TopicsExtracted
from sophia.domain.models import TopicLectureLink, TopicMapping, TopicSource


class TestTopicSource:
    """TopicSource enum values."""

    def test_values(self) -> None:
        assert TopicSource.LECTURE == "lecture"
        assert TopicSource.QUIZ == "quiz"
        assert TopicSource.MANUAL == "manual"


class TestTopicMapping:
    """TopicMapping frozen model."""

    def test_required_fields(self) -> None:
        tm = TopicMapping(topic="Linear Algebra", course_id=42)
        assert tm.topic == "Linear Algebra"
        assert tm.course_id == 42
        assert tm.source == TopicSource.LECTURE
        assert tm.frequency == 1

    def test_custom_fields(self) -> None:
        tm = TopicMapping(
            topic="Matrices",
            course_id=7,
            source=TopicSource.QUIZ,
            frequency=3,
        )
        assert tm.source == TopicSource.QUIZ
        assert tm.frequency == 3

    def test_frozen(self) -> None:
        tm = TopicMapping(topic="Test", course_id=1)
        with pytest.raises(ValidationError):
            tm.topic = "Changed"  # type: ignore[misc]


class TestTopicLectureLink:
    """TopicLectureLink frozen model."""

    def test_fields(self) -> None:
        link = TopicLectureLink(
            topic="Sorting",
            course_id=10,
            chunk_id="ep1_3",
            episode_id="ep1",
            score=0.87,
        )
        assert link.topic == "Sorting"
        assert link.chunk_id == "ep1_3"
        assert link.score == pytest.approx(0.87)  # pyright: ignore[reportUnknownMemberType]


class TestAthenaErrors:
    """Athena error hierarchy."""

    def test_athena_error_is_sophia_error(self) -> None:
        assert issubclass(AthenaError, SophiaError)

    def test_topic_extraction_error_is_athena_error(self) -> None:
        assert issubclass(TopicExtractionError, AthenaError)

    def test_topic_extraction_error_message(self) -> None:
        err = TopicExtractionError("LLM timeout")
        assert str(err) == "LLM timeout"


class TestAthenaEvents:
    """Athena domain events."""

    def test_topics_extracted(self) -> None:
        event = TopicsExtracted(course_id=42, topic_count=8, source="lecture")
        assert event.course_id == 42
        assert event.topic_count == 8
        assert event.source == "lecture"

    def test_topics_extracted_frozen(self) -> None:
        event = TopicsExtracted(course_id=1, topic_count=1, source="quiz")
        with pytest.raises(AttributeError):
            event.course_id = 99  # type: ignore[misc]

    def test_topic_lecture_linked(self) -> None:
        event = TopicLectureLinked(topic="OOP", course_id=5, chunk_count=3)
        assert event.topic == "OOP"
        assert event.chunk_count == 3


class TestCardReviewAttempt:
    """CardReviewAttempt frozen model."""

    def test_required_fields(self) -> None:
        from sophia.domain.models import CardReviewAttempt

        attempt = CardReviewAttempt(flashcard_id=7, success=True)
        assert attempt.flashcard_id == 7
        assert attempt.success is True
        assert attempt.id == 0
        assert attempt.reviewed_at == ""

    def test_custom_fields(self) -> None:
        from sophia.domain.models import CardReviewAttempt

        attempt = CardReviewAttempt(
            id=1, flashcard_id=7, success=False, reviewed_at="2026-03-16T12:00:00"
        )
        assert attempt.id == 1
        assert attempt.success is False
        assert attempt.reviewed_at == "2026-03-16T12:00:00"

    def test_frozen(self) -> None:
        from sophia.domain.models import CardReviewAttempt

        attempt = CardReviewAttempt(flashcard_id=1, success=True)
        with pytest.raises(ValidationError):
            attempt.success = False  # type: ignore[misc]


class TestCardReviewedEvent:
    """CardReviewed event."""

    def test_fields(self) -> None:
        from sophia.domain.events import CardReviewed

        event = CardReviewed(course_id=42, topic="Sorting", flashcard_id=7, success=True)
        assert event.course_id == 42
        assert event.topic == "Sorting"
        assert event.flashcard_id == 7
        assert event.success is True

    def test_frozen(self) -> None:
        from sophia.domain.events import CardReviewed

        event = CardReviewed(course_id=1, topic="T", flashcard_id=1, success=True)
        with pytest.raises(AttributeError):
            event.success = False  # type: ignore[misc]


class TestCardReviewError:
    """CardReviewError is in the Athena error hierarchy."""

    def test_is_athena_error(self) -> None:
        from sophia.domain.errors import CardReviewError

        assert issubclass(CardReviewError, AthenaError)

    def test_message(self) -> None:
        from sophia.domain.errors import CardReviewError

        err = CardReviewError("review failed")
        assert str(err) == "review failed"


class TestSelfExplanation:
    """SelfExplanation frozen model."""

    def test_required_fields(self) -> None:
        from sophia.domain.models import SelfExplanation

        exp = SelfExplanation(flashcard_id=7, student_explanation="I confused X with Y")
        assert exp.flashcard_id == 7
        assert exp.student_explanation == "I confused X with Y"
        assert exp.id == 0
        assert exp.scaffold_level == 3
        assert exp.created_at == ""

    def test_custom_fields(self) -> None:
        from sophia.domain.models import SelfExplanation

        exp = SelfExplanation(
            id=5,
            flashcard_id=7,
            student_explanation="Wrong because...",
            scaffold_level=1,
            created_at="2026-03-16T12:00:00",
        )
        assert exp.id == 5
        assert exp.scaffold_level == 1
        assert exp.created_at == "2026-03-16T12:00:00"

    def test_frozen(self) -> None:
        from sophia.domain.models import SelfExplanation

        exp = SelfExplanation(flashcard_id=1, student_explanation="text")
        with pytest.raises(ValidationError):
            exp.student_explanation = "new"  # type: ignore[misc]


class TestSelfExplanationRecordedEvent:
    """SelfExplanationRecorded event."""

    def test_fields(self) -> None:
        from sophia.domain.events import SelfExplanationRecorded

        event = SelfExplanationRecorded(
            course_id=42, topic="Sorting", flashcard_id=7, scaffold_level=3
        )
        assert event.course_id == 42
        assert event.topic == "Sorting"
        assert event.flashcard_id == 7
        assert event.scaffold_level == 3

    def test_frozen(self) -> None:
        from sophia.domain.events import SelfExplanationRecorded

        event = SelfExplanationRecorded(course_id=1, topic="T", flashcard_id=1, scaffold_level=0)
        with pytest.raises(AttributeError):
            event.scaffold_level = 2  # type: ignore[misc]


class TestReviewSchedule:
    """ReviewSchedule frozen model."""

    def test_required_fields(self) -> None:
        from sophia.domain.models import ReviewSchedule

        sched = ReviewSchedule(
            topic="Sorting", course_id=42, next_review_at="2026-03-17T12:00:00+00:00"
        )
        assert sched.topic == "Sorting"
        assert sched.course_id == 42
        assert sched.interval_index == 0
        assert sched.last_reviewed_at is None
        assert sched.score_at_last_review is None

    def test_custom_fields(self) -> None:
        from sophia.domain.models import ReviewSchedule

        sched = ReviewSchedule(
            topic="Hashing",
            course_id=7,
            interval_index=3,
            last_reviewed_at="2026-03-15T12:00:00+00:00",
            next_review_at="2026-03-29T12:00:00+00:00",
            score_at_last_review=0.85,
        )
        assert sched.interval_index == 3
        assert sched.score_at_last_review == pytest.approx(0.85)  # pyright: ignore[reportUnknownMemberType]

    def test_frozen(self) -> None:
        from sophia.domain.models import ReviewSchedule

        sched = ReviewSchedule(topic="T", course_id=1, next_review_at="2026-03-17T12:00:00+00:00")
        with pytest.raises(ValidationError):
            sched.topic = "Changed"  # type: ignore[misc]

    def test_interval_days_property(self) -> None:
        from sophia.domain.models import ReviewSchedule

        for idx, expected in enumerate([1, 3, 7, 14, 30]):
            sched = ReviewSchedule(
                topic="T",
                course_id=1,
                interval_index=idx,
                next_review_at="2026-03-17T12:00:00+00:00",
            )
            assert sched.interval_days == expected

    def test_interval_days_caps_at_max(self) -> None:
        from sophia.domain.models import ReviewSchedule

        sched = ReviewSchedule(
            topic="T", course_id=1, interval_index=99, next_review_at="2026-03-17T12:00:00+00:00"
        )
        assert sched.interval_days == 30

    def test_is_due_past(self) -> None:
        from sophia.domain.models import ReviewSchedule

        sched = ReviewSchedule(topic="T", course_id=1, next_review_at="2020-01-01T00:00:00+00:00")
        assert sched.is_due is True

    def test_is_due_future(self) -> None:
        from sophia.domain.models import ReviewSchedule

        sched = ReviewSchedule(topic="T", course_id=1, next_review_at="2099-01-01T00:00:00+00:00")
        assert sched.is_due is False


class TestReviewDueEvent:
    """ReviewDue event."""

    def test_fields(self) -> None:
        from sophia.domain.events import ReviewDue

        event = ReviewDue(topic="Sorting", course_id=42, interval_days=7)
        assert event.topic == "Sorting"
        assert event.course_id == 42
        assert event.interval_days == 7

    def test_frozen(self) -> None:
        from sophia.domain.events import ReviewDue

        event = ReviewDue(topic="T", course_id=1, interval_days=1)
        with pytest.raises(AttributeError):
            event.topic = "Changed"  # type: ignore[misc]


class TestReviewCompletedEvent:
    """ReviewCompleted event."""

    def test_fields(self) -> None:
        from sophia.domain.events import ReviewCompleted

        event = ReviewCompleted(topic="Sorting", course_id=42, score=0.85, next_interval_days=7)
        assert event.topic == "Sorting"
        assert event.score == pytest.approx(0.85)  # pyright: ignore[reportUnknownMemberType]
        assert event.next_interval_days == 7

    def test_frozen(self) -> None:
        from sophia.domain.events import ReviewCompleted

        event = ReviewCompleted(topic="T", course_id=1, score=0.5, next_interval_days=3)
        with pytest.raises(AttributeError):
            event.score = 1.0  # type: ignore[misc]


class TestTopicExtractorProtocol:
    """TopicExtractor protocol existence check."""

    def test_protocol_exists(self) -> None:
        from sophia.domain.ports import TopicExtractor

        assert hasattr(TopicExtractor, "extract_topics")
