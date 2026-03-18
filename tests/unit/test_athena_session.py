"""Tests for no-skip quiz (generation effect), session wiring, and reflection."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from sophia.services.athena_session import _run_quiz_no_skip, _run_reflection

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

            await _run_posttest(app, 42, "Algebra", console, ["Q1"], 0.5)

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

        output = console.file.getvalue()  # type: ignore[union-attr]
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
