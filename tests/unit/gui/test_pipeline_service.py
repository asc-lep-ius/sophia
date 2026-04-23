"""Tests for the selective GUI pipeline service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.domain.models import DownloadProgressEvent
from sophia.gui.services.hermes_service import EpisodeArtifacts
from sophia.gui.services.pipeline_service import (
    EpisodeStageSelection,
    PipelineRunner,
    PipelineStage,
    PipelineState,
    StageStatus,
    estimate_storage,
    normalize_stage_selection,
    validate_stage_prerequisites,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _artifact(
    episode_id: str,
    module_id: int,
    *,
    title: str | None = None,
    has_download: bool = True,
    has_transcript: bool = True,
    has_index: bool = False,
) -> EpisodeArtifacts:
    return EpisodeArtifacts(
        episode_id=episode_id,
        module_id=module_id,
        title=title or episode_id,
        download_status="completed" if has_download else "queued",
        transcription_status="completed" if has_transcript else None,
        index_status="completed" if has_index else None,
        has_download=has_download,
        has_transcript=has_transcript,
        has_index=has_index,
    )


class TestEstimateStorage:
    def test_zero_lectures(self) -> None:
        assert estimate_storage(0) == 0.0

    @pytest.mark.parametrize("count", [1, 5, 10])
    def test_scales_linearly(self, count: int) -> None:
        assert estimate_storage(count) == pytest.approx(estimate_storage(1) * count)


class TestPipelineState:
    def test_initial_state(self) -> None:
        state = PipelineState()
        assert state.running is False
        assert state.stage is None
        assert state.current_stage is None
        assert state.current_episode is None
        assert state.stage_progress == 0.0
        assert state.completed_episodes == 0
        assert state.total_episodes == 0
        assert state.error is None
        assert state.cancelled is False
        assert state.episode_progress == {}


class TestStageNormalization:
    def test_orders_and_deduplicates_requested_stages(self) -> None:
        ordered = normalize_stage_selection(
            {
                PipelineStage.INDEX,
                PipelineStage.DOWNLOAD,
                PipelineStage.TRANSCRIBE,
            }
        )
        assert ordered == (
            PipelineStage.DOWNLOAD,
            PipelineStage.TRANSCRIBE,
            PipelineStage.INDEX,
        )


class TestPrerequisiteValidation:
    @pytest.mark.asyncio
    async def test_index_without_transcript_warns(self) -> None:
        container = MagicMock()
        container.db = MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.get_episode_artifacts",
            new=AsyncMock(return_value={"e1": _artifact("e1", 10, has_transcript=False)}),
        ):
            runnable, warnings = await validate_stage_prerequisites(
                container,
                [EpisodeStageSelection("e1", (PipelineStage.INDEX,))],
            )

        assert runnable == []
        assert len(warnings) == 1
        assert warnings[0].episode_id == "e1"
        assert warnings[0].stage is PipelineStage.INDEX

    @pytest.mark.asyncio
    async def test_transcribe_without_download_warns(self) -> None:
        container = MagicMock()
        container.db = MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.get_episode_artifacts",
            new=AsyncMock(return_value={"e1": _artifact("e1", 10, has_download=False)}),
        ):
            runnable, warnings = await validate_stage_prerequisites(
                container,
                [("e1", {PipelineStage.TRANSCRIBE})],
            )

        assert runnable == []
        assert len(warnings) == 1
        assert warnings[0].stage is PipelineStage.TRANSCRIBE

    @pytest.mark.asyncio
    async def test_download_then_transcribe_then_index_is_allowed(self) -> None:
        container = MagicMock()
        container.db = MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.get_episode_artifacts",
            new=AsyncMock(
                return_value={"e1": _artifact("e1", 10, has_download=False, has_transcript=False)}
            ),
        ):
            runnable, warnings = await validate_stage_prerequisites(
                container,
                [
                    (
                        "e1",
                        {
                            PipelineStage.DOWNLOAD,
                            PipelineStage.TRANSCRIBE,
                            PipelineStage.INDEX,
                        },
                    )
                ],
            )

        assert warnings == []
        assert len(runnable) == 1
        assert runnable[0].stages_to_run == (
            PipelineStage.DOWNLOAD,
            PipelineStage.TRANSCRIBE,
            PipelineStage.INDEX,
        )


class TestSelectivePipelineRunner:
    @pytest.mark.asyncio
    async def test_routes_only_selected_stages(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        container.db = MagicMock()

        artifacts = {
            "e1": _artifact("e1", 10, title="Lecture 1", has_download=False, has_transcript=False),
            "e2": _artifact("e2", 11, title="Lecture 2", has_download=True, has_transcript=True),
        }

        download = AsyncMock(return_value=[MagicMock(episode_id="e1", status="completed")])
        transcribe = AsyncMock(
            return_value=[MagicMock(episode_id="e1", status="completed", segment_count=48)]
        )
        index = AsyncMock(
            return_value=[MagicMock(episode_id="e2", status="completed", chunk_count=12)]
        )

        with (
            patch(
                "sophia.gui.services.pipeline_service.get_episode_artifacts",
                new=AsyncMock(return_value=artifacts),
            ),
            patch("sophia.gui.services.pipeline_service.download_lectures", new=download),
            patch("sophia.gui.services.pipeline_service.transcribe_lectures", new=transcribe),
            patch("sophia.gui.services.pipeline_service.index_lectures", new=index),
            patch(
                "sophia.gui.services.pipeline_service.assign_lecture_numbers",
                new=AsyncMock(),
            ) as assign_numbers,
        ):
            success = await runner.run_selective_pipeline(
                container,
                [
                    ("e1", {PipelineStage.DOWNLOAD, PipelineStage.TRANSCRIBE}),
                    ("e2", {PipelineStage.INDEX}),
                ],
            )

        assert success is True
        download.assert_awaited_once()
        transcribe.assert_awaited_once()
        index.assert_awaited_once()
        download_args = download.await_args
        transcribe_args = transcribe.await_args
        index_args = index.await_args
        assert download_args is not None
        assert transcribe_args is not None
        assert index_args is not None
        assert download_args.kwargs["episode_ids"] == {"e1"}
        assert transcribe_args.kwargs["episode_ids"] == {"e1"}
        assert index_args.kwargs["episode_ids"] == {"e2"}
        assign_numbers.assert_awaited_once_with(container.db, 10)

        state = runner.get_state()
        assert state.running is False
        assert state.completed_episodes == 2
        assert (
            state.episode_progress["e1"].stage_states[PipelineStage.TRANSCRIBE].detail
            == "48 segments"
        )
        assert state.episode_progress["e2"].stage_states[PipelineStage.INDEX].detail == "12 chunks"

    @pytest.mark.asyncio
    async def test_failed_stage_does_not_count_as_successful_completion(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        container.db = MagicMock()

        with (
            patch(
                "sophia.gui.services.pipeline_service.get_episode_artifacts",
                new=AsyncMock(
                    return_value={
                        "e1": _artifact(
                            "e1",
                            10,
                            title="Lecture 1",
                            has_download=False,
                            has_transcript=False,
                        )
                    }
                ),
            ),
            patch(
                "sophia.gui.services.pipeline_service.download_lectures",
                new=AsyncMock(
                    return_value=[
                        MagicMock(episode_id="e1", status="failed", error="network error")
                    ]
                ),
            ),
            patch(
                "sophia.gui.services.pipeline_service.transcribe_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.index_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.assign_lecture_numbers",
                new=AsyncMock(),
            ),
        ):
            success = await runner.run_selective_pipeline(
                container,
                [("e1", {PipelineStage.DOWNLOAD})],
            )

        state = runner.get_state()
        assert success is False
        assert state.completed_episodes == 1
        assert state.successful_episodes == 0
        assert (
            state.episode_progress["e1"].stage_states[PipelineStage.DOWNLOAD].status
            is StageStatus.FAILED
        )

    @pytest.mark.asyncio
    async def test_rejected_selection_remains_visible_as_blocked_progress(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        container.db = MagicMock()

        with patch(
            "sophia.gui.services.pipeline_service.get_episode_artifacts",
            new=AsyncMock(
                return_value={
                    "e1": _artifact(
                        "e1",
                        10,
                        title="Lecture 1",
                        has_download=True,
                        has_transcript=False,
                    )
                }
            ),
        ):
            success = await runner.run_selective_pipeline(
                container,
                [("e1", {PipelineStage.INDEX})],
            )

        state = runner.get_state()
        assert success is False
        assert state.completed_episodes == 1
        assert state.successful_episodes == 0
        assert state.total_episodes == 1
        assert state.episode_progress["e1"].warnings == ["Indexing requires a transcript."]
        assert (
            state.episode_progress["e1"].stage_states[PipelineStage.INDEX].status
            is StageStatus.BLOCKED
        )
        assert (
            state.episode_progress["e1"].stage_states[PipelineStage.INDEX].detail
            == "Indexing requires a transcript."
        )

    @pytest.mark.asyncio
    async def test_download_progress_callback_updates_state(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        container.db = MagicMock()

        async def _download(*_args: object, **kwargs: object) -> list[MagicMock]:
            on_progress = cast(
                "Callable[[str, DownloadProgressEvent], None]",
                kwargs["on_progress"],
            )
            on_progress(
                "e1",
                DownloadProgressEvent(bytes_downloaded=50, total_bytes=100, speed_bps=1.0),
            )
            stage = runner.get_state().episode_progress["e1"].stage_states[PipelineStage.DOWNLOAD]
            assert stage.status is StageStatus.RUNNING
            assert stage.stage_progress == 0.5
            return [MagicMock(episode_id="e1", status="completed")]

        with (
            patch(
                "sophia.gui.services.pipeline_service.get_episode_artifacts",
                new=AsyncMock(
                    return_value={
                        "e1": _artifact("e1", 7, has_download=False, has_transcript=False)
                    }
                ),
            ),
            patch("sophia.gui.services.pipeline_service.download_lectures", side_effect=_download),
            patch(
                "sophia.gui.services.pipeline_service.transcribe_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.index_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.assign_lecture_numbers",
                new=AsyncMock(),
            ),
        ):
            success = await runner.run_selective_pipeline(
                container,
                [("e1", {PipelineStage.DOWNLOAD})],
            )

        assert success is True
        stage = runner.get_state().episode_progress["e1"].stage_states[PipelineStage.DOWNLOAD]
        assert stage.status is StageStatus.COMPLETED
        assert stage.stage_progress == 1.0

    @pytest.mark.asyncio
    async def test_cancel_mid_batch_marks_state_cancelled(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        container.db = MagicMock()

        async def _download(*_args: object, **kwargs: object) -> list[MagicMock]:
            runner.cancel()
            return [MagicMock(episode_id="e1", status="completed")]

        transcribe = AsyncMock(
            return_value=[MagicMock(episode_id="e1", status="completed", segment_count=3)]
        )

        with (
            patch(
                "sophia.gui.services.pipeline_service.get_episode_artifacts",
                new=AsyncMock(
                    return_value={
                        "e1": _artifact("e1", 3, has_download=False, has_transcript=False)
                    }
                ),
            ),
            patch("sophia.gui.services.pipeline_service.download_lectures", side_effect=_download),
            patch("sophia.gui.services.pipeline_service.transcribe_lectures", new=transcribe),
            patch(
                "sophia.gui.services.pipeline_service.index_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.assign_lecture_numbers",
                new=AsyncMock(),
            ),
        ):
            success = await runner.run_selective_pipeline(
                container,
                [("e1", {PipelineStage.DOWNLOAD, PipelineStage.TRANSCRIBE})],
            )

        assert success is False
        assert transcribe.await_count == 0
        state = runner.get_state()
        assert state.cancelled is True
        assert state.running is False
        assert (
            state.episode_progress["e1"].stage_states[PipelineStage.TRANSCRIBE].status
            is StageStatus.CANCELLED
        )

    @pytest.mark.asyncio
    async def test_lock_blocks_second_selective_run(self) -> None:
        runner = PipelineRunner()
        container = MagicMock()
        container.db = MagicMock()
        gate = asyncio.Event()

        async def _download(*_args: object, **_kwargs: object) -> list[MagicMock]:
            await gate.wait()
            return [MagicMock(episode_id="e1", status="completed")]

        with (
            patch(
                "sophia.gui.services.pipeline_service.get_episode_artifacts",
                new=AsyncMock(
                    return_value={
                        "e1": _artifact("e1", 1, has_download=False, has_transcript=False)
                    }
                ),
            ),
            patch("sophia.gui.services.pipeline_service.download_lectures", side_effect=_download),
            patch(
                "sophia.gui.services.pipeline_service.transcribe_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.index_lectures",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.gui.services.pipeline_service.assign_lecture_numbers",
                new=AsyncMock(),
            ),
        ):
            first = asyncio.create_task(
                runner.run_selective_pipeline(container, [("e1", {PipelineStage.DOWNLOAD})])
            )
            await asyncio.sleep(0.05)
            second = await runner.run_selective_pipeline(
                container,
                [("e1", {PipelineStage.DOWNLOAD})],
            )
            gate.set()
            await first

        assert second is False
