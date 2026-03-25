"""Tests for the study session page — pure helpers and constants."""

from __future__ import annotations

from sophia.domain.models import DifficultyLevel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_default_reflection_seconds(self) -> None:
        from sophia.gui.pages.study import _DEFAULT_REFLECTION_SECONDS

        assert _DEFAULT_REFLECTION_SECONDS == 30

    def test_autosave_interval(self) -> None:
        from sophia.gui.pages.study import _AUTOSAVE_INTERVAL_SECONDS

        assert _AUTOSAVE_INTERVAL_SECONDS == 10

    def test_pretest_count(self) -> None:
        from sophia.gui.pages.study import _PRETEST_COUNT

        assert _PRETEST_COUNT == 3

    def test_posttest_count(self) -> None:
        from sophia.gui.pages.study import _POSTTEST_COUNT

        assert _POSTTEST_COUNT == 3

    def test_difficulty_badge_colors_keys(self) -> None:
        from sophia.gui.pages.study import _DIFFICULTY_BADGE_COLORS

        assert set(_DIFFICULTY_BADGE_COLORS.keys()) == {
            DifficultyLevel.CUED,
            DifficultyLevel.EXPLAIN,
            DifficultyLevel.TRANSFER,
        }

    def test_difficulty_badge_cued_is_red(self) -> None:
        from sophia.gui.pages.study import _DIFFICULTY_BADGE_COLORS

        assert _DIFFICULTY_BADGE_COLORS[DifficultyLevel.CUED] == "red"

    def test_difficulty_badge_explain_is_orange(self) -> None:
        from sophia.gui.pages.study import _DIFFICULTY_BADGE_COLORS

        assert _DIFFICULTY_BADGE_COLORS[DifficultyLevel.EXPLAIN] == "orange"

    def test_difficulty_badge_transfer_is_green(self) -> None:
        from sophia.gui.pages.study import _DIFFICULTY_BADGE_COLORS

        assert _DIFFICULTY_BADGE_COLORS[DifficultyLevel.TRANSFER] == "green"

    def test_metacognitive_prompts_count(self) -> None:
        from sophia.gui.pages.study import _METACOGNITIVE_PROMPTS

        assert len(_METACOGNITIVE_PROMPTS) == 3

    def test_interleave_topic_bounds(self) -> None:
        from sophia.gui.pages.study import _MAX_INTERLEAVE_TOPICS, _MIN_INTERLEAVE_TOPICS

        assert _MIN_INTERLEAVE_TOPICS == 2
        assert _MAX_INTERLEAVE_TOPICS == 4


# ---------------------------------------------------------------------------
# _questions_complete
# ---------------------------------------------------------------------------


class TestQuestionsComplete:
    def test_all_answered_and_rated(self) -> None:
        from sophia.gui.pages.study import _questions_complete

        answers = {"0": "x=2", "1": "y=3", "2": "z=1"}
        confidence = {"0": 3, "1": 4, "2": 5}
        assert _questions_complete(answers, confidence, count=3) is True

    def test_missing_answer(self) -> None:
        from sophia.gui.pages.study import _questions_complete

        answers = {"0": "x=2", "1": "y=3"}
        confidence = {"0": 3, "1": 4, "2": 5}
        assert _questions_complete(answers, confidence, count=3) is False

    def test_missing_confidence(self) -> None:
        from sophia.gui.pages.study import _questions_complete

        answers = {"0": "x=2", "1": "y=3", "2": "z=1"}
        confidence = {"0": 3, "1": 4}
        assert _questions_complete(answers, confidence, count=3) is False

    def test_empty_answer_counts_as_missing(self) -> None:
        from sophia.gui.pages.study import _questions_complete

        answers = {"0": "x=2", "1": "", "2": "z=1"}
        confidence = {"0": 3, "1": 4, "2": 5}
        assert _questions_complete(answers, confidence, count=3) is False

    def test_whitespace_only_counts_as_missing(self) -> None:
        from sophia.gui.pages.study import _questions_complete

        answers = {"0": "x=2", "1": "   ", "2": "z=1"}
        confidence = {"0": 3, "1": 4, "2": 5}
        assert _questions_complete(answers, confidence, count=3) is False

    def test_zero_count_is_trivially_complete(self) -> None:
        from sophia.gui.pages.study import _questions_complete

        assert _questions_complete({}, {}, count=0) is True


# ---------------------------------------------------------------------------
# _build_session_id
# ---------------------------------------------------------------------------


class TestBuildSessionId:
    def test_single_topic(self) -> None:
        from sophia.gui.pages.study import _build_session_id

        sid = _build_session_id(42, ["Binary Search"], interleaved=False)
        assert sid == "42:Binary Search"

    def test_interleaved_multiple_topics(self) -> None:
        from sophia.gui.pages.study import _build_session_id

        sid = _build_session_id(7, ["Graph Theory", "Sorting", "Trees"], interleaved=True)
        assert sid.startswith("7:interleaved:")
        assert len(sid) > len("7:interleaved:")

    def test_interleaved_deterministic(self) -> None:
        from sophia.gui.pages.study import _build_session_id

        topics = ["Graph Theory", "Sorting", "Trees"]
        sid_a = _build_session_id(7, topics, interleaved=True)
        sid_b = _build_session_id(7, topics, interleaved=True)
        assert sid_a == sid_b

    def test_interleaved_order_independent(self) -> None:
        from sophia.gui.pages.study import _build_session_id

        sid_a = _build_session_id(7, ["A", "B", "C"], interleaved=True)
        sid_b = _build_session_id(7, ["C", "A", "B"], interleaved=True)
        assert sid_a == sid_b

    def test_different_course_ids_differ(self) -> None:
        from sophia.gui.pages.study import _build_session_id

        sid_a = _build_session_id(1, ["Topic"], interleaved=False)
        sid_b = _build_session_id(2, ["Topic"], interleaved=False)
        assert sid_a != sid_b


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_study_content_is_callable(self) -> None:
        from sophia.gui.pages.study import study_content

        assert callable(study_content)
