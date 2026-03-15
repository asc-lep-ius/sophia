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
        assert link.score == pytest.approx(0.87)


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


class TestTopicExtractorProtocol:
    """TopicExtractor protocol existence check."""

    def test_protocol_exists(self) -> None:
        from sophia.domain.ports import TopicExtractor

        assert hasattr(TopicExtractor, "extract_topics")
