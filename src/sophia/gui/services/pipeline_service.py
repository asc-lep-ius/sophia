"""Pipeline orchestration wrapper for the GUI — selective stages, state, estimation."""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from sophia.gui.services.hermes_service import get_episode_artifacts
from sophia.services.hermes_download import download_lectures
from sophia.services.hermes_index import index_lectures
from sophia.services.hermes_manage import assign_lecture_numbers
from sophia.services.hermes_pipeline import PipelineResult, run_pipeline
from sophia.services.hermes_transcribe import transcribe_lectures

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    import aiosqlite

    from sophia.domain.models import DownloadProgressEvent
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


class PipelineStage(enum.Enum):
    """Named stages for progress tracking."""

    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe"
    INDEX = "index"
    TOPICS = "topics"


class StageStatus(enum.Enum):
    """Lifecycle status for a selected episode stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


_SELECTIVE_STAGE_ORDER: tuple[PipelineStage, ...] = (
    PipelineStage.DOWNLOAD,
    PipelineStage.TRANSCRIBE,
    PipelineStage.INDEX,
)
_SUCCESSFUL_STAGE_STATUSES = {StageStatus.COMPLETED, StageStatus.SKIPPED}
_TERMINAL_STAGE_STATUSES = {
    StageStatus.COMPLETED,
    StageStatus.SKIPPED,
    StageStatus.BLOCKED,
    StageStatus.CANCELLED,
    StageStatus.FAILED,
}


@dataclass(slots=True)
class StageProgress:
    """Mutable state for a single progress bar."""

    current_stage: PipelineStage
    stage_progress: float = 0.0
    status: StageStatus = StageStatus.PENDING
    detail: str = ""


@dataclass(slots=True)
class EpisodeProgress:
    """Mutable progress state for one lecture in a selective batch."""

    episode_id: str
    module_id: int
    title: str
    stages_to_run: tuple[PipelineStage, ...]
    stage_states: dict[PipelineStage, StageProgress] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def is_finished(self) -> bool:
        """Return whether every selected stage reached a terminal state."""
        return bool(self.stages_to_run) and all(
            self.stage_states[stage].status in _TERMINAL_STAGE_STATUSES
            for stage in self.stages_to_run
        )

    def is_successful(self) -> bool:
        """Return whether every selected stage completed without failure."""
        return bool(self.stages_to_run) and all(
            self.stage_states[stage].status in _SUCCESSFUL_STAGE_STATUSES
            for stage in self.stages_to_run
        )

    @property
    def stages(self) -> dict[PipelineStage, StageProgress]:
        """Backwards-compatible alias for page bindings and older tests."""
        return self.stage_states


@dataclass(frozen=True, slots=True)
class EpisodeStageSelection:
    """Requested stage combination for one lecture."""

    episode_id: str
    stages_to_run: tuple[PipelineStage, ...]


@dataclass(frozen=True, slots=True)
class ValidatedEpisodeSelection:
    """Runnable lecture selection after prerequisite checks."""

    episode_id: str
    module_id: int
    title: str
    stages_to_run: tuple[PipelineStage, ...]


@dataclass(frozen=True, slots=True)
class PrerequisiteWarning:
    """Why a selected stage cannot run for a lecture."""

    episode_id: str
    stage: PipelineStage
    message: str


StageValidationIssue = PrerequisiteWarning


@dataclass
class PipelineState:
    """Tracks current selective pipeline status."""

    running: bool = False
    current_stage: PipelineStage | None = None
    stage_progress: float = 0.0
    current_episode: str | None = None
    status_message: str = ""
    completed_episodes: int = 0
    successful_episodes: int = 0
    total_episodes: int = 0
    error: str | None = None
    cancelled: bool = False
    episode_progress: dict[str, EpisodeProgress] = field(default_factory=dict)

    @property
    def stage(self) -> PipelineStage | None:
        """Backwards-compatible alias for older callers."""
        return self.current_stage

    @property
    def overall_progress(self) -> float:
        """Return overall batch progress as a 0.0-1.0 fraction."""
        if self.total_episodes == 0:
            return 0.0
        return self.completed_episodes / self.total_episodes


def estimate_storage(n_lectures: int, avg_duration_min: float = 90.0) -> float:
    """Estimate total GB needed for N lectures (audio + transcript + embeddings)."""
    if n_lectures == 0:
        return 0.0
    audio_gb = n_lectures * avg_duration_min * 1.5 / 1024
    transcript_gb = n_lectures * 0.002
    embedding_gb = n_lectures * 0.005
    return audio_gb + transcript_gb + embedding_gb


def normalize_stage_selection(stages: Collection[PipelineStage]) -> tuple[PipelineStage, ...]:
    """Return de-duplicated stages in pipeline execution order."""
    stage_set = set(stages)
    return tuple(stage for stage in _SELECTIVE_STAGE_ORDER if stage in stage_set)


def _coerce_selection(
    selection: EpisodeStageSelection | tuple[str, Collection[PipelineStage]],
) -> EpisodeStageSelection:
    if isinstance(selection, EpisodeStageSelection):
        return selection
    return EpisodeStageSelection(selection[0], normalize_stage_selection(selection[1]))


async def validate_stage_prerequisites(
    container: AppContainer,
    selections: Sequence[EpisodeStageSelection | tuple[str, Collection[PipelineStage]]],
) -> tuple[list[ValidatedEpisodeSelection], list[PrerequisiteWarning]]:
    """Resolve selective stage prerequisites against current episode artifacts."""
    requested: list[EpisodeStageSelection] = []
    warnings: list[PrerequisiteWarning] = []

    for raw_selection in selections:
        selection = _coerce_selection(raw_selection)
        if not selection.stages_to_run:
            warnings.append(
                PrerequisiteWarning(
                    episode_id=selection.episode_id,
                    stage=PipelineStage.DOWNLOAD,
                    message="Select at least one stage.",
                )
            )
            continue
        requested.append(selection)

    artifacts = await get_episode_artifacts(
        container.db,
        [selection.episode_id for selection in requested],
    )

    runnable: list[ValidatedEpisodeSelection] = []

    for selection in requested:
        artifact = artifacts.get(selection.episode_id)
        if artifact is None:
            warnings.append(
                PrerequisiteWarning(
                    episode_id=selection.episode_id,
                    stage=PipelineStage.DOWNLOAD,
                    message="Lecture metadata is unavailable.",
                )
            )
            continue

        effective_stages: list[PipelineStage] = []
        has_download = artifact.has_download
        has_transcript = artifact.has_transcript

        for stage in selection.stages_to_run:
            if stage is PipelineStage.DOWNLOAD:
                effective_stages.append(stage)
                has_download = True
                continue

            if stage is PipelineStage.TRANSCRIBE:
                if not has_download:
                    warnings.append(
                        PrerequisiteWarning(
                            episode_id=selection.episode_id,
                            stage=stage,
                            message="Transcription requires a downloaded lecture.",
                        )
                    )
                    continue
                effective_stages.append(stage)
                has_transcript = True
                continue

            if stage is PipelineStage.INDEX:
                if not has_transcript:
                    warnings.append(
                        PrerequisiteWarning(
                            episode_id=selection.episode_id,
                            stage=stage,
                            message="Indexing requires a transcript.",
                        )
                    )
                    continue
                effective_stages.append(stage)

        if effective_stages:
            runnable.append(
                ValidatedEpisodeSelection(
                    episode_id=selection.episode_id,
                    module_id=artifact.module_id,
                    title=artifact.title,
                    stages_to_run=tuple(effective_stages),
                )
            )

    return runnable, warnings


class PipelineRunner:
    """GUI-facing selective pipeline controller with a concurrency lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = PipelineState()
        self._cancel_event = asyncio.Event()
        self._stage_episode_ids: dict[PipelineStage, set[str]] = {}

    def get_state(self) -> PipelineState:
        return self._state

    def cancel(self) -> None:
        self._cancel_event.set()
        log.info("pipeline_cancel_requested")

    def is_cancelling(self) -> bool:
        return self._cancel_event.is_set()

    async def validate_stage_prerequisites(
        self,
        db: aiosqlite.Connection,
        selections: Sequence[EpisodeStageSelection | tuple[str, Collection[PipelineStage]]],
    ) -> list[StageValidationIssue]:
        """Return only the blocking warnings for the current stage selection."""
        requested = [_coerce_selection(selection) for selection in selections]
        if not requested:
            return []

        warnings: list[StageValidationIssue] = []
        artifacts = await get_episode_artifacts(
            db,
            [selection.episode_id for selection in requested],
        )

        for selection in requested:
            artifact = artifacts.get(selection.episode_id)
            if artifact is None:
                warnings.append(
                    StageValidationIssue(
                        episode_id=selection.episode_id,
                        stage=PipelineStage.DOWNLOAD,
                        message="Lecture metadata is unavailable.",
                    )
                )
                continue

            has_download = artifact.has_download
            has_transcript = artifact.has_transcript

            for stage in selection.stages_to_run:
                if stage is PipelineStage.DOWNLOAD:
                    has_download = True
                    continue
                if stage is PipelineStage.TRANSCRIBE:
                    if not has_download:
                        warnings.append(
                            StageValidationIssue(
                                episode_id=selection.episode_id,
                                stage=stage,
                                message=(
                                    "Transcription requires an existing "
                                    "download or Download selected"
                                ),
                            )
                        )
                        break
                    has_transcript = True
                    continue
                if stage is PipelineStage.INDEX and not has_transcript:
                    warnings.append(
                        StageValidationIssue(
                            episode_id=selection.episode_id,
                            stage=stage,
                            message=(
                                "Indexing requires an existing transcript or Transcribe selected"
                            ),
                        )
                    )
                    break

        return warnings

    async def start_single(
        self,
        container: AppContainer,
        module_id: int,
        episode_id: str,
    ) -> PipelineResult | None:
        """Run the full pipeline for one selected episode."""
        if self._lock.locked():
            log.warning("pipeline_already_running")
            return None

        async with self._lock:
            self._cancel_event.clear()
            self._state = PipelineState(running=True, current_episode=episode_id, total_episodes=1)
            try:
                result = await run_pipeline(
                    container,
                    module_id,
                    episode_ids={episode_id},
                    cancel_check=self._cancel_event.is_set,
                )
            except Exception as exc:
                log.exception("pipeline_single_failed", episode_id=episode_id)
                self._state.running = False
                self._state.error = str(exc)
                return None

            self._state.running = False
            self._state.cancelled = result.cancelled
            self._state.completed_episodes = 0 if result.cancelled else 1
            self._state.successful_episodes = 0 if result.cancelled else 1
            return result

    async def start_batch(
        self,
        container: AppContainer,
        module_id: int,
        episode_ids: list[str],
    ) -> bool:
        """Run the legacy module batch pipeline, optionally scoped to episode IDs."""
        if self._lock.locked():
            log.warning("pipeline_already_running")
            return False

        async with self._lock:
            self._cancel_event.clear()
            self._state = PipelineState(running=True, total_episodes=len(episode_ids))

            try:
                result = await run_pipeline(
                    container,
                    module_id,
                    episode_ids=set(episode_ids) if episode_ids else None,
                    cancel_check=self._cancel_event.is_set,
                )
            except Exception:
                log.exception("pipeline_batch_failed", module_id=module_id)
                self._state.running = False
                self._state.error = "batch pipeline failed"
                return False

            self._state.running = False
            self._state.cancelled = result.cancelled
            if not result.cancelled:
                self._state.completed_episodes = len(episode_ids)
                self._state.successful_episodes = len(episode_ids)
            return True

    async def run_selective_pipeline(
        self,
        container: AppContainer,
        selections: Sequence[EpisodeStageSelection | tuple[str, Collection[PipelineStage]]],
    ) -> bool:
        """Run the requested stages for the requested lectures only."""
        if self._lock.locked():
            log.warning("pipeline_already_running")
            return False

        async with self._lock:
            self._cancel_event.clear()
            requested = [_coerce_selection(selection) for selection in selections]
            validated, warnings = await validate_stage_prerequisites(container, requested)
            self._reset_selective_state(requested, validated, warnings)

            if not validated:
                self._state.running = False
                self._state.current_stage = None
                self._state.stage_progress = 1.0 if self._state.total_episodes else 0.0
                self._state.status_message = "No runnable stages"
                return False

            try:
                for stage in _SELECTIVE_STAGE_ORDER:
                    if self._cancel_event.is_set():
                        self._mark_cancelled()
                        return False

                    stage_selection = [
                        selection
                        for selection in validated
                        if stage in selection.stages_to_run
                        and self._can_run_stage(selection.episode_id, stage)
                    ]
                    if not stage_selection:
                        continue

                    self._state.current_stage = stage
                    self._state.stage_progress = 0.0
                    self._state.status_message = self._format_status_message(stage)

                    module_map: dict[int, set[str]] = {}
                    for selection in stage_selection:
                        module_map.setdefault(selection.module_id, set()).add(selection.episode_id)

                    for module_id, stage_episode_ids in module_map.items():
                        results = await self._run_stage(
                            container,
                            module_id,
                            stage,
                            stage_episode_ids,
                        )
                        if stage is PipelineStage.DOWNLOAD:
                            await assign_lecture_numbers(container.db, module_id)
                        self._apply_stage_results(stage, results)

                        if self._cancel_event.is_set():
                            self._mark_cancelled()
                            return False

                    self._state.stage_progress = 1.0
                    self._state.status_message = self._format_status_message(stage)

            except Exception as exc:
                log.exception("pipeline_selective_failed")
                self._state.running = False
                self._state.current_stage = None
                self._state.current_episode = None
                self._state.error = str(exc)
                self._state.status_message = str(exc)
                return False

            self._state.running = False
            self._state.current_stage = None
            self._state.current_episode = None
            self._state.stage_progress = 1.0
            self._state.status_message = "Pipeline complete"
            self._recalculate_episode_counts()
            return self._state.successful_episodes == self._state.total_episodes

    async def _run_stage(
        self,
        container: AppContainer,
        module_id: int,
        stage: PipelineStage,
        stage_episode_ids: set[str],
    ) -> list[object]:
        if stage is PipelineStage.DOWNLOAD:
            return await download_lectures(
                container,
                module_id,
                episode_ids=stage_episode_ids,
                on_progress=self._on_download_progress,
                cancel_check=self._cancel_event.is_set,
            )
        if stage is PipelineStage.TRANSCRIBE:
            return await transcribe_lectures(
                container,
                module_id,
                episode_ids=stage_episode_ids,
                on_start=self._on_transcribe_start,
                on_complete=self._on_transcribe_complete,
                cancel_check=self._cancel_event.is_set,
            )
        return await index_lectures(
            container,
            module_id,
            episode_ids=stage_episode_ids,
            on_start=self._on_index_start,
            on_complete=self._on_index_complete,
            cancel_check=self._cancel_event.is_set,
        )

    def _reset_selective_state(
        self,
        selections: Sequence[EpisodeStageSelection],
        validated: Sequence[ValidatedEpisodeSelection],
        warnings: Sequence[PrerequisiteWarning],
    ) -> None:
        warning_map: dict[str, list[PrerequisiteWarning]] = {}
        for warning in warnings:
            warning_map.setdefault(warning.episode_id, []).append(warning)

        validated_map = {selection.episode_id: selection for selection in validated}

        episode_progress: dict[str, EpisodeProgress] = {}
        for selection in selections:
            validated_selection = validated_map.get(selection.episode_id)
            episode_warnings = warning_map.get(selection.episode_id, [])
            stage_states = {
                stage: StageProgress(current_stage=stage) for stage in selection.stages_to_run
            }
            block_all_selected_stages = validated_selection is None and bool(episode_warnings)

            for stage, stage_progress in stage_states.items():
                blocked_message = next(
                    (
                        warning.message
                        for warning in episode_warnings
                        if warning.stage is stage
                    ),
                    None,
                )
                if blocked_message is None and block_all_selected_stages:
                    blocked_message = episode_warnings[0].message
                if blocked_message is None:
                    continue

                stage_progress.status = StageStatus.BLOCKED
                stage_progress.stage_progress = 1.0
                stage_progress.detail = blocked_message

            episode_progress[selection.episode_id] = EpisodeProgress(
                episode_id=selection.episode_id,
                module_id=validated_selection.module_id if validated_selection is not None else 0,
                title=(
                    validated_selection.title
                    if validated_selection is not None
                    else selection.episode_id
                ),
                stages_to_run=selection.stages_to_run,
                stage_states=stage_states,
                warnings=[warning.message for warning in episode_warnings],
            )

        self._state = PipelineState(
            running=True,
            total_episodes=len(selections),
            status_message="Preparing selective pipeline",
            episode_progress=episode_progress,
        )
        self._stage_episode_ids = {
            stage: {
                selection.episode_id for selection in validated if stage in selection.stages_to_run
            }
            for stage in _SELECTIVE_STAGE_ORDER
        }
        self._recalculate_episode_counts()

    def _can_run_stage(self, episode_id: str, stage: PipelineStage) -> bool:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return False

        for previous_stage in episode_progress.stages_to_run:
            if previous_stage is stage:
                return True
            previous_status = episode_progress.stage_states[previous_stage].status
            if previous_status not in _SUCCESSFUL_STAGE_STATUSES:
                self._block_following_stages(episode_id, previous_stage)
                return False
        return True

    def _block_following_stages(self, episode_id: str, failed_stage: PipelineStage) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return

        start_blocking = False
        for stage in episode_progress.stages_to_run:
            if stage is failed_stage:
                start_blocking = True
                continue
            if not start_blocking:
                continue
            stage_progress = episode_progress.stage_states[stage]
            if stage_progress.status is StageStatus.PENDING:
                stage_progress.status = StageStatus.BLOCKED
                stage_progress.stage_progress = 1.0
                stage_progress.detail = "Blocked by earlier stage failure"

    def _mark_cancelled(self) -> None:
        self._state.running = False
        self._state.cancelled = True
        self._state.status_message = "Pipeline cancelled"
        for episode_progress in self._state.episode_progress.values():
            for stage_progress in episode_progress.stage_states.values():
                if stage_progress.status in {StageStatus.PENDING, StageStatus.RUNNING}:
                    stage_progress.status = StageStatus.CANCELLED
        self._recalculate_episode_counts()

    def _update_stage_progress(self, stage: PipelineStage) -> None:
        episode_ids = self._stage_episode_ids.get(stage, set())
        if not episode_ids:
            self._state.stage_progress = 1.0
            return

        progress_total = 0.0
        for episode_id in episode_ids:
            episode_progress = self._state.episode_progress.get(episode_id)
            if episode_progress is None:
                continue
            progress_total += episode_progress.stage_states[stage].stage_progress

        self._state.stage_progress = progress_total / len(episode_ids)
        self._state.status_message = self._format_status_message(stage)

    def _format_status_message(self, stage: PipelineStage) -> str:
        lecture_number = min(self._state.completed_episodes + 1, self._state.total_episodes)
        stage_name = stage.value.capitalize()
        if self._state.current_episode is None:
            return (
                f"Processing lecture {lecture_number}/{self._state.total_episodes} — {stage_name}"
            )
        return (
            f"Processing lecture {lecture_number}/{self._state.total_episodes} — "
            f"{stage_name} ({self._state.current_episode})"
        )

    def _mark_episode_finished(self, episode_id: str) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None or not episode_progress.is_finished():
            return

        self._recalculate_episode_counts()

    def _recalculate_episode_counts(self) -> None:
        self._state.completed_episodes = sum(
            1 for progress in self._state.episode_progress.values() if progress.is_finished()
        )
        self._state.successful_episodes = sum(
            1 for progress in self._state.episode_progress.values() if progress.is_successful()
        )

    def _apply_stage_results(self, stage: PipelineStage, results: Sequence[object]) -> None:
        for result in results:
            episode_id = getattr(result, "episode_id", None)
            if episode_id is None:
                continue

            episode_progress = self._state.episode_progress.get(episode_id)
            if episode_progress is None or stage not in episode_progress.stage_states:
                continue

            stage_progress = episode_progress.stage_states[stage]
            result_status = getattr(result, "status", "completed")
            if result_status == "failed":
                stage_progress.status = StageStatus.FAILED
                stage_progress.stage_progress = 1.0
                stage_progress.detail = getattr(result, "error", "failed") or "failed"
                self._block_following_stages(episode_id, stage)
            elif result_status == "skipped":
                stage_progress.status = StageStatus.SKIPPED
                stage_progress.stage_progress = 1.0
                stage_progress.detail = "Already completed"
            else:
                stage_progress.status = StageStatus.COMPLETED
                stage_progress.stage_progress = 1.0
                if stage is PipelineStage.TRANSCRIBE:
                    stage_progress.detail = f"{getattr(result, 'segment_count', 0)} segments"
                elif stage is PipelineStage.INDEX:
                    stage_progress.detail = f"{getattr(result, 'chunk_count', 0)} chunks"
                else:
                    stage_progress.detail = "Completed"

            self._mark_episode_finished(episode_id)

        self._update_stage_progress(stage)

    def _on_download_progress(self, episode_id: str, event: DownloadProgressEvent) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return

        stage_progress = episode_progress.stage_states[PipelineStage.DOWNLOAD]
        stage_progress.status = StageStatus.RUNNING
        total_bytes = event.total_bytes or 0
        if total_bytes > 0:
            stage_progress.stage_progress = min(event.bytes_downloaded / total_bytes, 1.0)
            stage_progress.detail = f"{event.bytes_downloaded}/{total_bytes} bytes"
        else:
            stage_progress.detail = f"{event.bytes_downloaded} bytes"
        self._state.current_episode = episode_id
        self._update_stage_progress(PipelineStage.DOWNLOAD)

    def _on_transcribe_start(self, episode_id: str, title: str) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return

        stage_progress = episode_progress.stage_states[PipelineStage.TRANSCRIBE]
        stage_progress.status = StageStatus.RUNNING
        stage_progress.detail = title
        self._state.current_episode = episode_id
        self._update_stage_progress(PipelineStage.TRANSCRIBE)

    def _on_transcribe_complete(self, episode_id: str, segment_count: int) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return

        stage_progress = episode_progress.stage_states[PipelineStage.TRANSCRIBE]
        stage_progress.status = StageStatus.COMPLETED
        stage_progress.stage_progress = 1.0
        stage_progress.detail = f"{segment_count} segments"
        self._mark_episode_finished(episode_id)
        self._update_stage_progress(PipelineStage.TRANSCRIBE)

    def _on_index_start(self, episode_id: str, title: str) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return

        stage_progress = episode_progress.stage_states[PipelineStage.INDEX]
        stage_progress.status = StageStatus.RUNNING
        stage_progress.detail = title
        self._state.current_episode = episode_id
        self._update_stage_progress(PipelineStage.INDEX)

    def _on_index_complete(self, episode_id: str, chunk_count: int) -> None:
        episode_progress = self._state.episode_progress.get(episode_id)
        if episode_progress is None:
            return

        stage_progress = episode_progress.stage_states[PipelineStage.INDEX]
        stage_progress.status = StageStatus.COMPLETED
        stage_progress.stage_progress = 1.0
        stage_progress.detail = f"{chunk_count} chunks"
        self._mark_episode_finished(episode_id)
        self._update_stage_progress(PipelineStage.INDEX)
