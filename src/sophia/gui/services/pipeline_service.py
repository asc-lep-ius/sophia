"""Pipeline orchestration wrapper for the GUI — concurrency lock, state, estimation."""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from sophia.services.hermes_pipeline import PipelineResult, run_pipeline

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


class PipelineStage(enum.Enum):
    """Named stages for progress tracking."""

    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe"
    INDEX = "index"
    TOPICS = "topics"


@dataclass
class PipelineState:
    """Tracks current pipeline status — serialisable for storage persistence."""

    running: bool = False
    stage: PipelineStage | None = None
    current_episode: str | None = None
    completed_episodes: int = 0
    total_episodes: int = 0
    error: str | None = None
    cancelled: bool = False

    def mark_completed(self) -> PipelineState:
        return PipelineState(
            running=False,
            completed_episodes=self.completed_episodes,
            total_episodes=self.total_episodes,
        )

    def mark_failed(self, error: str) -> PipelineState:
        return PipelineState(
            running=False,
            error=error,
            completed_episodes=self.completed_episodes,
            total_episodes=self.total_episodes,
        )

    def mark_cancelled(self) -> PipelineState:
        return PipelineState(
            running=False,
            cancelled=True,
            completed_episodes=self.completed_episodes,
            total_episodes=self.total_episodes,
        )


def estimate_storage(n_lectures: int, avg_duration_min: float = 90.0) -> float:
    """Estimate total GB needed for N lectures (audio + transcript + embeddings)."""
    if n_lectures == 0:
        return 0.0
    audio_gb = n_lectures * avg_duration_min * 1.5 / 1024
    transcript_gb = n_lectures * 0.002
    embedding_gb = n_lectures * 0.005
    return audio_gb + transcript_gb + embedding_gb


class PipelineRunner:
    """GUI-facing pipeline controller with concurrency lock and cancellation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = PipelineState()
        self._cancel_requested = False

    def get_state(self) -> PipelineState:
        return self._state

    def cancel(self) -> None:
        self._cancel_requested = True
        log.info("pipeline_cancel_requested")

    async def start_single(
        self,
        container: AppContainer,
        module_id: int,
        episode_id: str,
    ) -> PipelineResult | None:
        """Run full-module pipeline triggered from a single episode.

        Each stage internally skips already-completed episodes, so triggering
        from one episode effectively processes all pending episodes in the module.
        Returns ``None`` when the lock is held or on failure.
        """
        if self._lock.locked():
            log.warning("pipeline_already_running")
            return None

        async with self._lock:
            self._cancel_requested = False
            self._state = PipelineState(
                running=True,
                stage=PipelineStage.DOWNLOAD,
                current_episode=episode_id,
                total_episodes=1,
            )
            try:
                result = await run_pipeline(container, module_id)
                self._state = self._state.mark_completed()
                return result
            except Exception as exc:
                log.exception("pipeline_single_failed", episode_id=episode_id)
                self._state = self._state.mark_failed(str(exc))
                return None

    async def start_batch(
        self,
        container: AppContainer,
        module_id: int,
        episode_ids: list[str],
    ) -> bool:
        """Run the full-module pipeline once for all pending episodes.

        ``episode_ids`` is used only for progress tracking — the underlying
        ``run_pipeline`` processes every pending episode in the module in a
        single invocation (each stage skips already-completed work).
        Returns ``False`` if the lock is already held.
        """
        if self._lock.locked():
            log.warning("pipeline_already_running")
            return False

        async with self._lock:
            self._cancel_requested = False
            total = len(episode_ids)
            self._state = PipelineState(
                running=True,
                stage=PipelineStage.DOWNLOAD,
                total_episodes=total,
            )

            try:
                await run_pipeline(container, module_id)
            except Exception:
                log.exception("pipeline_batch_failed", module_id=module_id)
                self._state = self._state.mark_failed("batch pipeline failed")
                return False

            if self._cancel_requested:
                self._state = self._state.mark_cancelled()
            else:
                self._state = PipelineState(
                    running=False,
                    completed_episodes=total,
                    total_episodes=total,
                )
            return True
