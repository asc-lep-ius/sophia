"""Tests for no-skip quiz (generation effect) and session wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.services.athena_session import _run_quiz_no_skip

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
