"""Tests for Hermes CLI lecture commands — Phase 6 additions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.domain.models import CourseMaterial
from sophia.services.hermes_manage import EpisodeStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_episode_status(
    episode_id: str = "ep-001",
    title: str = "Lecture 1",
    download_status: str = "completed",
    *,
    lecture_number: int | None = 1,
    skip_reason: str | None = None,
    transcription_status: str | None = "completed",
    index_status: str | None = "completed",
) -> EpisodeStatus:
    return EpisodeStatus(
        episode_id=episode_id,
        title=title,
        download_status=download_status,
        skip_reason=skip_reason,
        transcription_status=transcription_status,
        index_status=index_status,
        lecture_number=lecture_number,
    )


def _make_material(
    mat_id: int = 1,
    course_id: int = 42,
    name: str = "Slides Week 1",
    *,
    url: str = "https://tuwel.example.com/file.pdf",
    mimetype: str = "application/pdf",
    file_size_bytes: int = 102400,
    status: str = "pending",
    chunk_count: int = 0,
) -> CourseMaterial:
    return CourseMaterial(
        id=mat_id,
        course_id=course_id,
        module_id=100,
        name=name,
        url=url,
        mimetype=mimetype,
        file_size_bytes=file_size_bytes,
        status=status,
        chunk_count=chunk_count,
    )


def _mock_container(*, db_side_effects: list | None = None) -> MagicMock:
    """Build a minimal mock AppContainer."""
    container = MagicMock()
    container.db = AsyncMock()
    container.moodle = AsyncMock()
    if db_side_effects:
        container.db.execute = AsyncMock(side_effect=db_side_effects)
    return container


# ---------------------------------------------------------------------------
# lectures status — shows # and Materials columns
# ---------------------------------------------------------------------------


class TestStatusTableColumns:
    """The status table must include lecture number and material count."""

    @pytest.mark.asyncio
    async def test_status_includes_lecture_number_column(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The status table renders the lecture_number from EpisodeStatus."""
        from sophia.cli.lectures import lectures_status

        statuses = [
            _make_episode_status("ep-001", "Lecture 1", lecture_number=1),
            _make_episode_status("ep-002", "Lecture 2", lecture_number=2),
            _make_episode_status("ep-003", "Intro", lecture_number=None),
        ]

        # Mock the material count query: returns (count,) for each episode's module
        mat_cursor = AsyncMock()
        mat_cursor.fetchone = AsyncMock(return_value=(3,))

        container = _mock_container()
        container.db.execute = AsyncMock(return_value=mat_cursor)

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch("sophia.cli._resolver.resolve_module_id", AsyncMock(return_value=42)),
            patch(
                "sophia.services.hermes_manage.get_pipeline_status",
                AsyncMock(return_value=statuses),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await lectures_status(module_id="42")

        captured = capsys.readouterr()
        # Lecture numbers appear in the # column
        assert "1" in captured.out
        assert "2" in captured.out
        # Material count (3) and column header should appear
        assert "3" in captured.out


# ---------------------------------------------------------------------------
# lectures materials — new subcommand
# ---------------------------------------------------------------------------


class TestMaterialsCommand:
    """The `sophia lectures materials` subcommand scrapes and lists course materials."""

    @pytest.mark.asyncio
    async def test_materials_displays_scraped_results(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """materials command calls scrape_course_materials and shows a Rich table."""
        from sophia.cli.lectures import materials

        scraped = [_make_material(1, name="Slides Week 1"), _make_material(2, name="Handout")]

        # DB query for existing materials returns those + the new ones
        existing_cursor = AsyncMock()
        existing_cursor.fetchall = AsyncMock(
            return_value=[
                ("Slides Week 1", "https://x.pdf", "application/pdf", 102400, "pending", 0),
                ("Handout", "https://y.pdf", "application/pdf", 102400, "pending", 0),
            ]
        )

        container = _mock_container()
        container.db.execute = AsyncMock(return_value=existing_cursor)

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.material_index.scrape_course_materials",
                AsyncMock(return_value=scraped),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await materials(course_id=42)

        captured = capsys.readouterr()
        assert "Slides Week 1" in captured.out
        assert "Handout" in captured.out

    @pytest.mark.asyncio
    async def test_materials_with_index_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When --index is set, index_materials is called and chunk count displayed."""
        from sophia.cli.lectures import materials

        existing_cursor = AsyncMock()
        existing_cursor.fetchall = AsyncMock(
            return_value=[
                ("Slides", "https://x.pdf", "application/pdf", 1024, "pending", 0),
            ]
        )

        container = _mock_container()
        container.db.execute = AsyncMock(return_value=existing_cursor)

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.material_index.scrape_course_materials",
                AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.services.material_index.index_materials",
                AsyncMock(return_value=15),
            ) as mock_index,
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await materials(course_id=42, index=True)

        mock_index.assert_called_once()
        captured = capsys.readouterr()
        assert "15" in captured.out


# ---------------------------------------------------------------------------
# lectures process — --materials flag
# ---------------------------------------------------------------------------


class TestProcessMaterialsFlag:
    """The process command optionally indexes materials after the pipeline."""

    @pytest.mark.asyncio
    async def test_process_materials_flag_calls_index_materials(self) -> None:
        """When --materials is set, run_pipeline is called with index_materials=True."""
        from sophia.services.hermes_pipeline import run_pipeline

        container = MagicMock()

        with (
            patch("sophia.services.hermes_pipeline.download_lectures", AsyncMock(return_value=[])),
            patch(
                "sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])
            ),
            patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
            patch(
                "sophia.services.hermes_pipeline.extract_topics_from_lectures",
                AsyncMock(return_value=[]),
            ),
            patch(
                "sophia.services.hermes_pipeline.assign_lecture_numbers",
                AsyncMock(),
            ),
            patch(
                "sophia.services.material_index.index_materials",
                AsyncMock(return_value=10),
            ) as mock_index_mat,
        ):
            result = await run_pipeline(container, module_id=42, index_materials=True, course_id=99)

        mock_index_mat.assert_called_once_with(container, 99)
        assert result.material_chunks == 10


# ---------------------------------------------------------------------------
# lectures search — --source filter
# ---------------------------------------------------------------------------


class TestSearchSourceFilter:
    """The search command accepts --source to filter by lecture/pdf/all."""

    @pytest.mark.asyncio
    async def test_search_lectures_passes_source_filter(self) -> None:
        """search_lectures forwards source_filter to the knowledge store."""
        from sophia.services.hermes_index import search_lectures

        container = MagicMock()
        container.db = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("ep-001", "Lecture 1")])
        container.db.execute = AsyncMock(return_value=cursor)
        container.settings.config_dir = "/tmp/test"
        container.settings.data_dir = MagicMock()
        container.settings.data_dir.__truediv__ = MagicMock(return_value="/tmp/test/knowledge")

        mock_embedder = MagicMock()
        mock_embedder.embed_query = MagicMock(return_value=[0.1, 0.2])
        mock_store = MagicMock()
        mock_store.search = MagicMock(return_value=[])

        with (
            patch("sophia.services.hermes_index._create_embedder", return_value=mock_embedder),
            patch("sophia.services.hermes_index._create_store", return_value=mock_store),
        ):
            await search_lectures(container, 42, "test query", source_filter="pdf")

        # Verify source_filter was passed to store.search
        mock_store.search.assert_called_once()
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["source_filter"] == "pdf"

    @pytest.mark.asyncio
    async def test_search_result_includes_source_field(self) -> None:
        """LectureSearchResult should include a source field."""
        from sophia.domain.models import KnowledgeChunk
        from sophia.services.hermes_index import search_lectures

        chunk = KnowledgeChunk(
            chunk_id="c1",
            episode_id="ep-001",
            chunk_index=0,
            text="Some content",
            start_time=10.0,
            end_time=20.0,
            source="pdf",
        )

        container = MagicMock()
        container.db = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[("ep-001", "Lecture 1")])
        container.db.execute = AsyncMock(return_value=cursor)
        container.settings.config_dir = "/tmp/test"
        container.settings.data_dir = MagicMock()
        container.settings.data_dir.__truediv__ = MagicMock(return_value="/tmp/test/knowledge")

        mock_embedder = MagicMock()
        mock_embedder.embed_query = MagicMock(return_value=[0.1, 0.2])
        mock_store = MagicMock()
        mock_store.search = MagicMock(return_value=[(chunk, 0.95)])

        with (
            patch("sophia.services.hermes_index._create_embedder", return_value=mock_embedder),
            patch("sophia.services.hermes_index._create_store", return_value=mock_store),
        ):
            results = await search_lectures(container, 42, "test query")

        assert len(results) == 1
        assert results[0].source == "pdf"
