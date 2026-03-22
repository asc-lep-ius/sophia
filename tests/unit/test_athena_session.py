"""Tests for no-skip quiz (generation effect), session wiring, reflection, and interleaving."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from sophia.domain.models import ConfidenceRating, ReviewSchedule, TopicMapping, TopicSource
from sophia.services.athena_session import _run_quiz, _run_quiz_no_skip, _run_reflection

# ---------------------------------------------------------------------------
# _run_quiz (with skip option)
# ---------------------------------------------------------------------------


class TestRunQuiz:
    def test_correct_answer_counted(self) -> None:
        console = MagicMock()
        with (
            patch("rich.prompt.Prompt.ask", return_value="my answer"),
            patch("rich.prompt.Confirm.ask", return_value=True),
        ):
            result = _run_quiz(["What is X?"], console)
        assert result == 1

    def test_skip_not_counted(self) -> None:
        console = MagicMock()
        with (
            patch("rich.prompt.Prompt.ask", return_value="skip"),
            patch("rich.prompt.Confirm.ask", return_value=True),
        ):
            result = _run_quiz(["Q1"], console)
        assert result == 0

    def test_wrong_answer_not_counted(self) -> None:
        console = MagicMock()
        with (
            patch("rich.prompt.Prompt.ask", return_value="wrong"),
            patch("rich.prompt.Confirm.ask", return_value=False),
        ):
            result = _run_quiz(["Q1"], console)
        assert result == 0

    def test_mixed_answers(self) -> None:
        """Multiple questions: one correct, one skipped, one wrong."""
        console = MagicMock()
        with (
            patch("rich.prompt.Prompt.ask", side_effect=["answer", "skip", "wrong"]),
            patch("rich.prompt.Confirm.ask", side_effect=[True, False]),
        ):
            result = _run_quiz(["Q1", "Q2", "Q3"], console)
        assert result == 1

    def test_empty_questions(self) -> None:
        console = MagicMock()
        result = _run_quiz([], console)
        assert result == 0


# ---------------------------------------------------------------------------
# _run_quiz_no_skip
# ---------------------------------------------------------------------------


class TestRunQuizNoSkip:
    def test_run_quiz_no_skip_requires_answer(self) -> None:
        """Empty answers are rejected until a real answer is given."""
        console = MagicMock()
        questions = ["What is X?"]

        with (
            patch(
                "rich.prompt.Prompt.ask",
                side_effect=["", "my answer"],
            ) as mock_ask,
            patch(
                "rich.prompt.Confirm.ask",
                return_value=False,
            ),
        ):
            result = _run_quiz_no_skip(questions, console)

        assert mock_ask.call_count == 2
        assert result == 0

    def test_run_quiz_no_skip_shows_encoding_message(self) -> None:
        """Console output includes the generation-effect encouragement."""
        console = MagicMock()
        questions = ["What is X?"]

        with (
            patch(
                "rich.prompt.Prompt.ask",
                return_value="some answer",
            ),
            patch(
                "rich.prompt.Confirm.ask",
                return_value=True,
            ),
        ):
            _run_quiz_no_skip(questions, console)

        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "strengthens encoding" in printed

    def test_run_quiz_no_skip_counts_correct(self) -> None:
        """Correct self-assessments are counted."""
        console = MagicMock()
        questions = ["Q1", "Q2"]

        with (
            patch(
                "rich.prompt.Prompt.ask",
                return_value="answer",
            ),
            patch(
                "rich.prompt.Confirm.ask",
                side_effect=[True, False],
            ),
        ):
            result = _run_quiz_no_skip(questions, console)

        assert result == 1


# ---------------------------------------------------------------------------
# Pretest uses no-skip, posttest allows skip
# ---------------------------------------------------------------------------


class TestSessionWiring:
    @pytest.mark.asyncio
    async def test_pretest_uses_no_skip_quiz(self) -> None:
        """_run_pretest calls _run_quiz_no_skip instead of _run_quiz."""
        mock_gen = AsyncMock(return_value=["Q1", "Q2", "Q3"])
        mock_ratings = AsyncMock(return_value=[])

        with (
            patch(
                "sophia.services.athena_study.generate_study_questions",
                mock_gen,
            ),
            patch(
                "sophia.services.athena_session._run_quiz_no_skip",
                return_value=2,
            ) as mock_no_skip,
            patch(
                "sophia.services.athena_session._run_quiz",
            ) as mock_skip,
            patch(
                "sophia.services.athena_session.get_confidence_ratings",
                mock_ratings,
            ),
        ):
            from sophia.services.athena_session import _run_pretest

            app = MagicMock()
            app.db = MagicMock()
            console = MagicMock()

            await _run_pretest(app, 42, "Algebra", console)

        mock_no_skip.assert_called_once()
        mock_skip.assert_not_called()

    @pytest.mark.asyncio
    async def test_posttest_still_allows_skip(self) -> None:
        """_run_posttest uses the original _run_quiz (with skip)."""
        mock_gen = AsyncMock(return_value=["Q1", "Q2", "Q3"])
        mock_ratings = AsyncMock(return_value=[])

        with (
            patch(
                "sophia.services.athena_study.generate_study_questions",
                mock_gen,
            ),
            patch(
                "sophia.services.athena_session._run_quiz",
                return_value=2,
            ) as mock_skip,
            patch(
                "sophia.services.athena_session._run_quiz_no_skip",
            ) as mock_no_skip,
            patch(
                "sophia.services.athena_session.get_confidence_ratings",
                mock_ratings,
            ),
        ):
            from sophia.services.athena_session import _run_posttest

            app = MagicMock()
            app.db = MagicMock()
            console = MagicMock()

            await _run_posttest(app, 42, "Algebra", console, ["Q1"])

        mock_skip.assert_called_once()
        mock_no_skip.assert_not_called()


# ---------------------------------------------------------------------------
# Reflection prompt and delay
# ---------------------------------------------------------------------------


class TestRunReflection:
    @pytest.mark.asyncio
    async def test_reflection_shown_with_default_delay(self) -> None:
        """Reflection prompt prints and sleep is called for each second."""
        console = Console(file=io.StringIO(), force_terminal=True)
        mock_target = "sophia.services.athena_session.asyncio_sleep"
        with patch(mock_target, new_callable=AsyncMock) as mock_sleep:
            await _run_reflection(console, 3)

        output = str(console.file.getvalue())  # type: ignore[union-attr]
        assert "reflect" in output.lower()
        assert mock_sleep.await_count == 3

    @pytest.mark.asyncio
    async def test_reflection_skipped_when_delay_zero(self) -> None:
        """Zero delay means no output and no sleep."""
        console = Console(file=io.StringIO(), force_terminal=True)
        mock_target = "sophia.services.athena_session.asyncio_sleep"
        with patch(mock_target, new_callable=AsyncMock) as mock_sleep:
            await _run_reflection(console, 0)

        output = console.file.getvalue()  # type: ignore[union-attr]
        assert output == ""
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reflection_prompt_contains_metacognitive_questions(self) -> None:
        """Output includes metacognitive keywords."""
        console = Console(file=io.StringIO(), force_terminal=True)
        with patch("sophia.services.athena_session.asyncio_sleep", new_callable=AsyncMock):
            await _run_reflection(console, 1)

        output = console.file.getvalue()  # type: ignore[union-attr]
        assert "hardest" in output
        assert "uncertain" in output


class TestFeedbackDelayPassthrough:
    @pytest.mark.asyncio
    async def test_feedback_delay_passed_through_session(self) -> None:
        """run_interactive_session accepts and forwards feedback_delay."""
        with (
            patch(
                "sophia.services.athena_session._run_pretest",
                new_callable=AsyncMock,
                return_value=(0.5, ["Q1"]),
            ),
            patch(
                "sophia.services.athena_session._run_study_phase",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session._run_posttest",
                new_callable=AsyncMock,
                return_value=0.8,
            ),
            patch(
                "sophia.services.athena_session._run_reflection",
                new_callable=AsyncMock,
            ) as mock_reflect,
            patch(
                "sophia.services.athena_session._run_flashcard_phase",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session.start_study_session",
                new_callable=AsyncMock,
                return_value=MagicMock(id=1),
            ),
            patch(
                "sophia.services.athena_session.complete_study_session",
                new_callable=AsyncMock,
            ),
            patch("rich.prompt.Confirm.ask", return_value=True),
        ):
            from sophia.services.athena_session import run_interactive_session

            app = MagicMock()
            app.db = MagicMock()
            console = MagicMock()

            await run_interactive_session(app, 42, "Algebra", console, feedback_delay=10)

        mock_reflect.assert_awaited_once_with(console, 10)


# ---------------------------------------------------------------------------
# Topic selection for interleaving
# ---------------------------------------------------------------------------


def _make_blind_spot(topic: str, predicted: float = 0.8, actual: float = 0.3) -> ConfidenceRating:
    return ConfidenceRating(
        topic=topic,
        course_id=1,
        predicted=predicted,
        actual=actual,
        rated_at="",
    )


def _make_review(topic: str) -> ReviewSchedule:
    return ReviewSchedule(topic=topic, course_id=1, next_review_at="2020-01-01T00:00:00+00:00")


def _make_topic(topic: str) -> TopicMapping:
    return TopicMapping(topic=topic, course_id=1, source=TopicSource.LECTURE, frequency=1)


class TestSelectInterleaveTopics:
    @pytest.mark.asyncio
    async def test_uses_blind_spots(self) -> None:
        """Blind-spot topics are selected first."""
        from sophia.services.athena_session import _select_interleave_topics

        app = MagicMock()
        app.db = MagicMock()
        with (
            patch(
                "sophia.services.athena_session.get_blind_spots",
                new_callable=AsyncMock,
                return_value=[_make_blind_spot("Algebra"), _make_blind_spot("Calculus")],
            ),
            patch(
                "sophia.services.athena_session.get_due_reviews",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_study.get_course_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            topics = await _select_interleave_topics(app, 1)

        assert topics == ["Algebra", "Calculus"]

    @pytest.mark.asyncio
    async def test_falls_back_to_due(self) -> None:
        """When no blind spots, due reviews are used."""
        from sophia.services.athena_session import _select_interleave_topics

        app = MagicMock()
        app.db = MagicMock()
        with (
            patch(
                "sophia.services.athena_session.get_blind_spots",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_session.get_due_reviews",
                new_callable=AsyncMock,
                return_value=[_make_review("Stats"), _make_review("Logic")],
            ),
            patch(
                "sophia.services.athena_study.get_course_topics",
                new_callable=AsyncMock,
                return_value=[_make_topic("Stats"), _make_topic("Logic"), _make_topic("Algebra")],
            ),
        ):
            topics = await _select_interleave_topics(app, 1)

        assert topics == ["Stats", "Logic"]

    @pytest.mark.asyncio
    async def test_max_3(self) -> None:
        """At most max_topics (default 3) are returned."""
        from sophia.services.athena_session import _select_interleave_topics

        app = MagicMock()
        app.db = MagicMock()
        many = [_make_blind_spot(f"T{i}") for i in range(5)]
        with (
            patch(
                "sophia.services.athena_session.get_blind_spots",
                new_callable=AsyncMock,
                return_value=many,
            ),
            patch(
                "sophia.services.athena_session.get_due_reviews",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_study.get_course_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            topics = await _select_interleave_topics(app, 1)

        assert len(topics) <= 3


# ---------------------------------------------------------------------------
# Interleaved session
# ---------------------------------------------------------------------------


class TestInterleavedSession:
    @pytest.mark.asyncio
    async def test_runs_multiple_topics(self) -> None:
        """Interleaved session generates questions for each topic."""
        from sophia.services.athena_session import run_interleaved_session

        app = MagicMock()
        app.db = MagicMock()
        console = MagicMock()
        gen_calls: list[str] = []

        async def fake_gen(_app: object, _cid: int, topic: str, **kw: object) -> list[str]:
            gen_calls.append(topic)
            return [f"Q on {topic}"]

        with (
            patch(
                "sophia.services.athena_session._select_interleave_topics",
                new_callable=AsyncMock,
                return_value=["Algebra", "Calculus", "Stats"],
            ),
            patch(
                "sophia.services.athena_session.get_confidence_ratings",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_study.generate_study_questions",
                side_effect=fake_gen,
            ),
            patch(
                "sophia.services.athena_study.get_lecture_context",
                new_callable=AsyncMock,
                return_value="content",
            ),
            patch(
                "sophia.services.athena_session._run_quiz_no_skip",
                return_value=1,
            ),
            patch(
                "sophia.services.athena_session._run_quiz",
                return_value=2,
            ),
            patch(
                "sophia.services.athena_session._run_reflection",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session._run_flashcard_phase",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session.start_study_session",
                new_callable=AsyncMock,
                return_value=MagicMock(id=1),
            ),
            patch(
                "sophia.services.athena_session.complete_study_session",
                new_callable=AsyncMock,
            ),
        ):
            await run_interleaved_session(app, 1, console=console)

        # Questions generated for each of the 3 topics (pre + post = 6 calls)
        assert set(gen_calls) == {"Algebra", "Calculus", "Stats"}


# ---------------------------------------------------------------------------
# Interleave tip after single-topic session
# ---------------------------------------------------------------------------


class TestInterleaveTip:
    @pytest.mark.asyncio
    async def test_tip_shown_after_single_topic(self) -> None:
        """Single-topic session ends with interleave tip."""
        with (
            patch(
                "sophia.services.athena_session._run_pretest",
                new_callable=AsyncMock,
                return_value=(0.5, ["Q1"]),
            ),
            patch(
                "sophia.services.athena_session._run_study_phase",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session._run_posttest",
                new_callable=AsyncMock,
                return_value=0.8,
            ),
            patch(
                "sophia.services.athena_session._run_reflection",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session._run_flashcard_phase",
                new_callable=AsyncMock,
            ),
            patch(
                "sophia.services.athena_session.start_study_session",
                new_callable=AsyncMock,
                return_value=MagicMock(id=1),
            ),
            patch(
                "sophia.services.athena_session.complete_study_session",
                new_callable=AsyncMock,
            ),
            patch("rich.prompt.Confirm.ask", return_value=True),
        ):
            from sophia.services.athena_session import run_interactive_session

            app = MagicMock()
            app.db = MagicMock()
            console = MagicMock()

            await run_interactive_session(app, 42, "Algebra", console, feedback_delay=0)

        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "--interleave" in printed


# ---------------------------------------------------------------------------
# CLI --interleave flag
# ---------------------------------------------------------------------------


class TestInterleaveFlag:
    @pytest.mark.asyncio
    async def test_dispatches_correctly(self) -> None:
        """CLI session command dispatches to run_interleaved_session when flag set."""
        mock_interleaved = AsyncMock()

        with (
            patch("sophia.infra.di.create_app") as mock_create_app,
            patch(
                "sophia.cli._resolver.resolve_module_id",
                new_callable=AsyncMock,
                return_value=42,
            ),
            patch(
                "sophia.services.athena_study.get_course_topics",
                new_callable=AsyncMock,
                return_value=[_make_topic("Algebra")],
            ),
            patch(
                "sophia.services.athena_session.run_interleaved_session",
                mock_interleaved,
            ),
            patch(
                "sophia.services.athena_session.run_interactive_session",
                new_callable=AsyncMock,
            ) as mock_single,
        ):
            container = MagicMock()
            container.moodle = MagicMock()
            container.db = MagicMock()
            mock_ctx_mgr = AsyncMock()
            mock_ctx_mgr.__aenter__ = AsyncMock(return_value=container)
            mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)
            mock_create_app.return_value = mock_ctx_mgr

            from sophia.cli.study import study_session

            await study_session("42", topic="Algebra", interleave=True)

        mock_interleaved.assert_awaited_once()
        mock_single.assert_not_awaited()


# ---------------------------------------------------------------------------
# _run_pretest — TopicExtractionError fallback
# ---------------------------------------------------------------------------


class TestPretestFallback:
    @pytest.mark.asyncio
    async def test_topic_extraction_error_uses_fallback_questions(self) -> None:
        """TopicExtractionError in generate_study_questions triggers fallback."""
        from sophia.domain.errors import TopicExtractionError
        from sophia.services.athena_session import _run_pretest

        async def _raise_extraction_error(*args: object, **kwargs: object) -> None:
            raise TopicExtractionError("LLM unavailable")

        with (
            patch(
                "sophia.services.athena_study.generate_study_questions",
                side_effect=_raise_extraction_error,
            ),
            patch(
                "sophia.services.athena_session.get_confidence_ratings",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_session._run_quiz_no_skip",
                return_value=1,
            ) as mock_quiz,
        ):
            app = MagicMock()
            console = MagicMock()
            _score, qs = await _run_pretest(app, 42, "Algebra", console)

        # Fallback questions should have been generated
        assert len(qs) == 3
        assert all("Algebra" in q for q in qs)
        mock_quiz.assert_called_once()


# ---------------------------------------------------------------------------
# _run_study_phase — no lecture content
# ---------------------------------------------------------------------------


class TestStudyPhaseNoContent:
    @pytest.mark.asyncio
    async def test_no_content_shows_warning(self) -> None:
        """When get_lecture_context returns empty string, a warning is printed."""
        from sophia.services.athena_session import _run_study_phase

        with patch(
            "sophia.services.athena_study.get_lecture_context",
            new_callable=AsyncMock,
            return_value="",
        ):
            app = MagicMock()
            console = MagicMock()
            await _run_study_phase(app, 42, "Algebra", console)

        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "No lecture content" in printed

    @pytest.mark.asyncio
    async def test_with_content_shows_panel(self) -> None:
        """When lecture content exists, a panel is printed (not the warning)."""
        from sophia.services.athena_session import _run_study_phase

        with patch(
            "sophia.services.athena_study.get_lecture_context",
            new_callable=AsyncMock,
            return_value="Here is some lecture text about sorting algorithms...",
        ):
            app = MagicMock()
            console = MagicMock()
            await _run_study_phase(app, 42, "Sorting", console)

        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "No lecture content" not in printed


# ---------------------------------------------------------------------------
# _select_interleave_topics — all-topics fallback
# ---------------------------------------------------------------------------


class TestSelectInterleaveTopicsFallbackAllTopics:
    @pytest.mark.asyncio
    async def test_falls_back_to_all_course_topics(self) -> None:
        """When blind spots and due reviews give <2 topics, falls back to get_course_topics."""
        from sophia.services.athena_session import _select_interleave_topics

        app = MagicMock()
        app.db = MagicMock()
        with (
            patch(
                "sophia.services.athena_session.get_blind_spots",
                new_callable=AsyncMock,
                return_value=[_make_blind_spot("Algebra")],
            ),
            patch(
                "sophia.services.athena_session.get_due_reviews",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_study.get_course_topics",
                new_callable=AsyncMock,
                return_value=[
                    _make_topic("Algebra"),
                    _make_topic("Calculus"),
                    _make_topic("Stats"),
                ],
            ),
        ):
            topics = await _select_interleave_topics(app, 1)

        # Should include Algebra (blind spot) + Calculus and/or Stats from all-topics
        assert len(topics) >= 2
        assert "Algebra" in topics

    @pytest.mark.asyncio
    async def test_no_topics_at_all_returns_empty(self) -> None:
        """When all sources return nothing, returns empty list."""
        from sophia.services.athena_session import _select_interleave_topics

        app = MagicMock()
        app.db = MagicMock()
        with (
            patch(
                "sophia.services.athena_session.get_blind_spots",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_session.get_due_reviews",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "sophia.services.athena_study.get_course_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            topics = await _select_interleave_topics(app, 1)

        assert topics == []


# ---------------------------------------------------------------------------
# run_interactive_session — skip study phase
# ---------------------------------------------------------------------------


class TestRunInteractiveSessionSkipStudy:
    @pytest.mark.asyncio
    async def test_skip_study_phase_saves_pretest_only(self) -> None:
        """If user declines to continue after pre-test, session saves with pre-test score only."""
        from sophia.services.athena_session import run_interactive_session

        with (
            patch(
                "sophia.services.athena_session._run_pretest",
                new_callable=AsyncMock,
                return_value=(0.33, ["Q1"]),
            ),
            patch(
                "sophia.services.athena_session.start_study_session",
                new_callable=AsyncMock,
                return_value=MagicMock(id=7),
            ),
            patch(
                "sophia.services.athena_session.complete_study_session",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch(
                "sophia.services.athena_session._run_study_phase",
                new_callable=AsyncMock,
            ) as mock_study,
            patch("rich.prompt.Confirm.ask", return_value=False),
        ):
            app = MagicMock()
            console = MagicMock()
            await run_interactive_session(app, 42, "Algebra", console)

        mock_study.assert_not_awaited()
        mock_complete.assert_awaited_once_with(app.db, 7, 0.33, 0.33)
