"""Tests for the JobRegistry — user-scoped background job tracking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from sophia.gui.services.job_registry import JobRegistry


@pytest.fixture()
def mock_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``app.storage.user`` to a plain dict for isolated tests."""
    storage: dict[str, Any] = {}
    mock_app_storage = MagicMock()
    mock_app_storage.user = storage
    monkeypatch.setattr("sophia.gui.services.job_registry.app.storage", mock_app_storage)
    return storage


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_creates_queued_job(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        job_id = registry.register("Hermes: Process Analysis L3")

        assert job_id  # non-empty UUID string
        active = registry.get_active()
        assert len(active) == 1
        assert active[0].id == job_id
        assert active[0].name == "Hermes: Process Analysis L3"
        assert active[0].status == "queued"
        assert active[0].progress == 0.0
        assert active[0].started_at is None
        assert active[0].completed_at is None
        assert active[0].error is None


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_status_to_running(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        job_id = registry.register("Download lectures")
        registry.update(job_id, status="running", progress=0.3)

        active = registry.get_active()
        assert len(active) == 1
        assert active[0].status == "running"
        assert active[0].progress == pytest.approx(0.3)
        assert active[0].started_at is not None

    @pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
    def test_update_sets_completed_at_on_terminal_status(
        self, mock_storage: dict[str, Any], terminal_status: str
    ) -> None:
        registry = JobRegistry()
        job_id = registry.register("Index lectures")
        registry.update(job_id, status="running")
        registry.update(job_id, status=terminal_status)

        history = registry.get_history()
        assert len(history) == 1
        assert history[0].completed_at is not None
        assert history[0].status == terminal_status

    def test_update_nonexistent_job_raises(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        with pytest.raises(KeyError):
            registry.update("nonexistent-id", status="running")


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_sets_cancelled_status(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        job_id = registry.register("Topic extraction")
        registry.update(job_id, status="running")
        registry.cancel(job_id)

        history = registry.get_history()
        assert len(history) == 1
        assert history[0].status == "cancelled"
        assert history[0].completed_at is not None

    def test_cancel_nonexistent_job_raises(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        with pytest.raises(KeyError):
            registry.cancel("nonexistent-id")


# ---------------------------------------------------------------------------
# get_active
# ---------------------------------------------------------------------------


class TestGetActive:
    def test_returns_only_active_jobs(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        id1 = registry.register("Job A")
        _id2 = registry.register("Job B")
        id3 = registry.register("Job C")

        registry.update(id1, status="running")
        registry.update(id3, status="completed")

        active = registry.get_active()
        names = {j.name for j in active}
        assert names == {"Job A", "Job B"}

    def test_sorted_by_started_at(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        id1 = registry.register("First")
        id2 = registry.register("Second")

        registry.update(id1, status="running")
        registry.update(id2, status="running")

        active = registry.get_active()
        assert active[0].name == "First"
        assert active[1].name == "Second"


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    def test_returns_terminal_jobs(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        id1 = registry.register("Done")
        id2 = registry.register("Failed")
        _id3 = registry.register("Still running")

        registry.update(id1, status="completed")
        registry.update(id2, status="failed", error="timeout")
        registry.update(_id3, status="running")

        history = registry.get_history()
        names = {j.name for j in history}
        assert names == {"Done", "Failed"}

    def test_newest_first(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        id1 = registry.register("Older")
        id2 = registry.register("Newer")

        registry.update(id1, status="completed")
        registry.update(id2, status="completed")

        history = registry.get_history()
        assert history[0].name == "Newer"
        assert history[1].name == "Older"

    def test_respects_limit(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        for i in range(5):
            jid = registry.register(f"Job {i}")
            registry.update(jid, status="completed")

        history = registry.get_history(limit=3)
        assert len(history) == 3


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


class TestPrune:
    def test_removes_old_entries(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        jid = registry.register("Ancient job")
        registry.update(jid, status="completed")

        # Manually backdate completed_at
        jobs = mock_storage["jobs"]
        jobs[0]["completed_at"] = (datetime.now(UTC) - timedelta(days=10)).isoformat()

        removed = registry.prune(max_age_days=7)
        assert removed == 1
        assert registry.get_history() == []

    def test_keeps_recent_entries(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        jid = registry.register("Recent job")
        registry.update(jid, status="completed")

        removed = registry.prune(max_age_days=7)
        assert removed == 0
        assert len(registry.get_history()) == 1

    def test_keeps_active_jobs(self, mock_storage: dict[str, Any]) -> None:
        registry = JobRegistry()
        jid = registry.register("Running job")
        registry.update(jid, status="running")

        # Manually backdate started_at
        jobs = mock_storage["jobs"]
        jobs[0]["started_at"] = (datetime.now(UTC) - timedelta(days=10)).isoformat()

        removed = registry.prune(max_age_days=7)
        assert removed == 0
        assert len(registry.get_active()) == 1
