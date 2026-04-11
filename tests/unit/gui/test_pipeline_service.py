"""Tests for the pipeline service — storage estimation, state management, concurrency."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.gui.services.pipeline_service import (
    PipelineRunner,
    PipelineStage,
    PipelineState,
    estimate_storage,
)
from sophia.services.hermes_pipeline import PipelineResult

# --- estimate_storage --------------------------------------------------------


class TestEstimateStorage:
    """Pure function that estimates disk usage for N lectures."""

    def test_single_lecture_default_duration(self) -> None:
        gb = estimate_storage(1)
        assert gb == pytest.approx(1 * 90 * 1.5 / 1024 + 0.002 + 0.005, rel=1e-3)

    def test_multiple_lectures(self) -> None:
        gb = estimate_storage(5)
        single = 90 * 1.5 / 1024 + 0.002 + 0.005
        assert gb == pytest.approx(5 * single, rel=1e-3)

    def test_zero_lectures(self) -> None:
        assert estimate_storage(0) == 0.0

    def test_custom_duration(self) -> None:
        gb = estimate_storage(2, avg_duration_min=60.0)
        audio = 2 * 60 * 1.5 / 1024
        transcript = 2 * 0.002
        embedding = 2 * 0.005
        assert gb == pytest.approx(audio + transcript + embedding, rel=1e-3)

    @pytest.mark.parametrize("n", [1, 10, 50])
    def test_scales_linearly(self, n: int) -> None:
        single = estimate_storage(1)
        assert estimate_storage(n) == pytest.approx(n * single, rel=1e-6)


# --- PipelineState -----------------------------------------------------------


class TestPipelineState:
    """Dataclass that tracks pipeline progress."""

    def test_initial_state(self) -> None:
        state = PipelineState()
        assert state.running is False
        assert state.stage is None
        assert state.current_episode is None
        assert state.completed_episodes == 0
        assert state.total_episodes == 0
        assert state.error is None
        assert state.cancelled is False

    def test_update_progress(self) -> None:
        state = PipelineState(
            running=True,
            stage=PipelineStage.DOWNLOAD,
            current_episode="e1",
            completed_episodes=2,
            total_episodes=5,
        )
        assert state.running is True
        assert state.stage == PipelineStage.DOWNLOAD
        assert state.current_episode == "e1"
        assert state.completed_episodes == 2
        assert state.total_episodes == 5

    def test_mark_completed(self) -> None:
        state = PipelineState(running=True, stage=PipelineStage.INDEX)
        completed = state.mark_completed()
        assert completed.running is False
        assert completed.stage is None
        assert completed.current_episode is None

    def test_mark_failed(self) -> None:
        state = PipelineState(running=True, stage=PipelineStage.TRANSCRIBE)
        failed = state.mark_failed("Whisper OOM")
        assert failed.running is False
        assert failed.error == "Whisper OOM"

    def test_mark_cancelled(self) -> None:
        state = PipelineState(running=True, stage=PipelineStage.DOWNLOAD)
        cancelled = state.mark_cancelled()
        assert cancelled.running is False
        assert cancelled.cancelled is True


# --- PipelineRunner concurrency lock ----------------------------------------


class TestPipelineRunnerConcurrency:
    """Verify that only one pipeline can run at a time."""

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()

        # Make the pipeline block until we release it
        gate = asyncio.Event()

        async def _slow_pipeline(*_args: object, **_kwargs: object) -> MagicMock:
            await gate.wait()
            return MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            side_effect=_slow_pipeline,
        ):
            # Start first pipeline
            task = asyncio.create_task(runner.start_single(container, 1, "e1"))

            # Give the task time to acquire the lock
            await asyncio.sleep(0.05)

            # Second attempt should fail immediately
            result = await runner.start_single(container, 1, "e2")
            assert result is None

            # Release first pipeline
            gate.set()
            first_result = await task
            assert first_result is not None

    @pytest.mark.asyncio
    async def test_lock_releases_after_completion(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()

        mock_result = MagicMock()
        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result1 = await runner.start_single(container, 1, "e1")
            assert result1 is not None

            result2 = await runner.start_single(container, 1, "e2")
            assert result2 is not None

    @pytest.mark.asyncio
    async def test_cancel_during_batch(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        gate = asyncio.Event()

        async def _slow_pipeline(*_args: object, **_kwargs: object) -> PipelineResult:
            gate.set()
            await asyncio.sleep(0.2)
            return PipelineResult()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            side_effect=_slow_pipeline,
        ):
            task = asyncio.create_task(
                runner.start_batch(container, 1, ["e1", "e2", "e3"]),
            )
            await gate.wait()
            runner.cancel()
            await task

        state = runner.get_state()
        assert state.cancelled is True

    @pytest.mark.asyncio
    async def test_get_state_during_run(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        gate = asyncio.Event()

        async def _wait_pipeline(*_args: object, **_kwargs: object) -> MagicMock:
            gate.set()
            await asyncio.sleep(0.1)
            return MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            side_effect=_wait_pipeline,
        ):
            task = asyncio.create_task(runner.start_single(container, 1, "e1"))
            await gate.wait()

            state = runner.get_state()
            assert state.running is True

            await task


# --- Issue 2: start_single return type should be PipelineResult | None -------


class TestStartSingleReturnType:
    """start_single should return PipelineResult on success, None when locked."""

    @pytest.mark.asyncio
    async def test_returns_pipeline_result_on_success(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        expected = PipelineResult()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            result = await runner.start_single(container, 1, "e1")

        assert isinstance(result, PipelineResult)

    @pytest.mark.asyncio
    async def test_returns_none_when_locked(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        gate = asyncio.Event()

        async def _block(*_a: object, **_kw: object) -> PipelineResult:
            await gate.wait()
            return PipelineResult()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            side_effect=_block,
        ):
            task = asyncio.create_task(runner.start_single(container, 1, "e1"))
            await asyncio.sleep(0.05)
            result = await runner.start_single(container, 1, "e2")
            assert result is None
            gate.set()
            await task

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await runner.start_single(container, 1, "e1")

        assert result is None
        assert runner.get_state().error == "boom"


# --- Issue 3: start_batch calls run_pipeline exactly once --------------------


class TestStartBatchSingleCall:
    """start_batch must call run_pipeline once, not N times."""

    @pytest.mark.asyncio
    async def test_calls_run_pipeline_once(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()

        mock_run = AsyncMock(return_value=PipelineResult())
        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            mock_run,
        ):
            await runner.start_batch(container, 42, ["e1", "e2", "e3"])

        mock_run.assert_awaited_once_with(container, 42)

    @pytest.mark.asyncio
    async def test_marks_all_episodes_completed(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.run_pipeline",
            new_callable=AsyncMock,
            return_value=PipelineResult(),
        ):
            await runner.start_batch(container, 1, ["e1", "e2", "e3"])

        state = runner.get_state()
        assert state.running is False
        assert state.completed_episodes == 3
        assert state.total_episodes == 3
