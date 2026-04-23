"""Tests for the Lectures page helper logic."""

from __future__ import annotations

from typing import TypedDict, cast
from unittest.mock import MagicMock, patch

import pytest

from sophia.gui.pages.lectures import (
    LectureRecord,
    StageToggleState,
    build_course_tree_nodes,
    build_stage_render_states,
    build_stage_warnings,
    course_episode_ids,
    is_hermes_setup_complete,
    lecture_needs_selected_stages,
    select_all_unprocessed_episode_ids,
    selected_stages,
)
from sophia.gui.services.pipeline_service import (
    EpisodeProgress,
    PipelineStage,
    PipelineState,
    StageProgress,
    StageStatus,
)
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE
from sophia.services.hermes_manage import EpisodeStatus


class _LectureTreeLeaf(TypedDict):
    id: str
    label: str


class _CourseTreeNode(TypedDict):
    id: str
    label: str
    children: list[_LectureTreeLeaf]


def _ep(
    *,
    episode_id: str = "e1",
    title: str = "Lecture 1",
    lecture_number: int | None = None,
    dl: str = "completed",
    tr: str | None = "completed",
    idx: str | None = "completed",
) -> EpisodeStatus:
    return EpisodeStatus(
        episode_id=episode_id,
        title=title,
        download_status=dl,
        skip_reason=None,
        transcription_status=tr,
        index_status=idx,
        lecture_number=lecture_number,
    )


def _record(
    episode: EpisodeStatus,
    *,
    module_id: int = 1,
    course_name: str = "Course A",
) -> LectureRecord:
    return LectureRecord(module_id=module_id, course_name=course_name, episode=episode)


class TestIsHermesSetupComplete:
    def test_returns_false_when_key_missing(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is False

    def test_returns_true_when_key_is_true(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {USER_HERMES_SETUP_COMPLETE: True}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is True


class TestStageSelection:
    def test_selected_stages_respects_checkbox_order(self) -> None:
        toggle_state = StageToggleState(download=False, transcribe=True, index=True)
        assert selected_stages(toggle_state) == (
            PipelineStage.TRANSCRIBE,
            PipelineStage.INDEX,
        )

    def test_lecture_needs_selected_stages(self) -> None:
        episode = _ep(dl="completed", tr="completed", idx=None)
        assert (
            lecture_needs_selected_stages(
                episode,
                (PipelineStage.INDEX,),
            )
            is True
        )
        assert (
            lecture_needs_selected_stages(
                episode,
                (PipelineStage.DOWNLOAD,),
            )
            is False
        )


class TestSelectionHelpers:
    def test_select_all_unprocessed_excludes_processed_lectures(self) -> None:
        records = [
            _record(_ep(episode_id="e1", idx="completed")),
            _record(_ep(episode_id="e2", idx=None)),
            _record(_ep(episode_id="e3", dl="queued", tr=None, idx=None)),
        ]

        selected = select_all_unprocessed_episode_ids(records, (PipelineStage.INDEX,))

        assert selected == {"e2", "e3"}

    def test_course_episode_ids_returns_only_requested_course(self) -> None:
        records = [
            _record(_ep(episode_id="e1"), course_name="Course A"),
            _record(_ep(episode_id="e2"), course_name="Course A"),
            _record(_ep(episode_id="e3"), course_name="Course B"),
        ]

        assert course_episode_ids(records, "Course A") == {"e1", "e2"}


class TestWarningHelpers:
    def test_transcribe_without_download_warns(self) -> None:
        records_by_id = {"e1": _record(_ep(episode_id="e1", dl="queued", tr=None, idx=None))}

        warnings = build_stage_warnings(
            records_by_id,
            {"e1"},
            (PipelineStage.TRANSCRIBE,),
        )

        assert warnings == ["Lecture 1: Transcribe requires Download."]

    def test_index_without_transcript_warns(self) -> None:
        records_by_id = {"e1": _record(_ep(episode_id="e1", dl="completed", tr=None, idx=None))}

        warnings = build_stage_warnings(
            records_by_id,
            {"e1"},
            (PipelineStage.INDEX,),
        )

        assert warnings == [
            "Lecture 1: Index requires Transcribe or an existing transcript.",
        ]

    def test_download_and_transcribe_satisfy_local_prerequisites(self) -> None:
        records_by_id = {"e1": _record(_ep(episode_id="e1", dl="queued", tr=None, idx=None))}

        warnings = build_stage_warnings(
            records_by_id,
            {"e1"},
            (PipelineStage.DOWNLOAD, PipelineStage.TRANSCRIBE),
        )

        assert warnings == []


class TestTreeHelpers:
    def test_build_course_tree_nodes_groups_by_course(self) -> None:
        records = [
            _record(_ep(episode_id="e1", lecture_number=1), course_name="Course A"),
            _record(_ep(episode_id="e2", lecture_number=2), course_name="Course A"),
            _record(_ep(episode_id="e3"), course_name="Course B"),
        ]

        nodes = cast("list[_CourseTreeNode]", build_course_tree_nodes(records))

        assert len(nodes) == 2
        assert nodes[0]["label"] == "Course A (2)"
        assert nodes[0]["children"][0]["id"] == "episode:e1"
        assert nodes[0]["children"][0]["label"] == "#1 Lecture 1"


class TestStageRenderHelpers:
    def test_build_stage_render_states_uses_live_progress_state(self) -> None:
        pipeline_state = PipelineState(
            episode_progress={
                "e1": EpisodeProgress(
                    episode_id="e1",
                    module_id=1,
                    title="Lecture 1",
                    stages_to_run=(PipelineStage.DOWNLOAD,),
                    stage_states={
                        PipelineStage.DOWNLOAD: StageProgress(
                            current_stage=PipelineStage.DOWNLOAD,
                            stage_progress=0.5,
                            status=StageStatus.RUNNING,
                            detail="50/100 bytes",
                        )
                    },
                )
            }
        )

        render_states = build_stage_render_states(
            "e1",
            (PipelineStage.DOWNLOAD,),
            pipeline_state,
        )

        assert render_states == [
            pytest.param(
                render_states[0],
                id="live-progress",
            ).values[0]
        ]
        assert render_states[0].symbol == "🔄"
        assert render_states[0].progress == 0.5
        assert render_states[0].detail == "50/100 bytes"

    def test_build_stage_render_states_defaults_to_pending(self) -> None:
        render_states = build_stage_render_states(
            "missing",
            (PipelineStage.TRANSCRIBE,),
            PipelineState(),
        )

        assert render_states[0].symbol == "⏳"
        assert render_states[0].status == "pending"
        assert render_states[0].progress == 0.0
