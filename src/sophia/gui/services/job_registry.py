"""Lightweight user-scoped job registry backed by NiceGUI user storage.

Tracks background operations (pipeline processing, deadline sync, topic
extraction) so the Settings page can show progress and history.

This is NOT a task queue — it is purely observational bookkeeping.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from nicegui import app

from sophia.gui.state.storage_map import USER_JOBS

_ACTIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})
_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


@dataclass
class JobEntry:
    """Single tracked background job."""

    id: str
    name: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: float
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None


def _deserialize(raw: dict[str, Any]) -> JobEntry:
    """Convert a storage dict back to a JobEntry."""
    return JobEntry(
        id=raw["id"],
        name=raw["name"],
        status=raw["status"],
        progress=raw.get("progress", 0.0),
        started_at=datetime.fromisoformat(raw["started_at"]) if raw.get("started_at") else None,
        completed_at=(
            datetime.fromisoformat(raw["completed_at"]) if raw.get("completed_at") else None
        ),
        error=raw.get("error"),
    )


def _jobs_list() -> list[dict[str, Any]]:
    """Return the raw jobs list from storage, initialising if absent."""
    jobs = app.storage.user.get(USER_JOBS)
    if jobs is None:
        app.storage.user[USER_JOBS] = []
        return app.storage.user[USER_JOBS]
    return jobs


def _find_index(jobs: list[dict[str, Any]], job_id: str) -> int:
    """Return the index of a job by ID, or raise KeyError."""
    for i, j in enumerate(jobs):
        if j["id"] == job_id:
            return i
    msg = f"Job {job_id!r} not found"
    raise KeyError(msg)


class JobRegistry:
    """User-scoped job tracking via ``app.storage.user['jobs']``.

    All methods read from / write to ``app.storage.user`` directly so that
    multiple browser tabs see consistent data.
    """

    def register(self, name: str) -> str:
        """Create a new queued job entry. Returns the job ID (UUID)."""
        job_id = str(uuid.uuid4())
        entry = JobEntry(
            id=job_id,
            name=name,
            status="queued",
            progress=0.0,
            started_at=None,
            completed_at=None,
            error=None,
        )
        jobs = _jobs_list()
        jobs.append(asdict(entry))
        return job_id

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        error: str | None = None,
    ) -> None:
        """Update a job's status, progress, or error message."""
        jobs = _jobs_list()
        idx = _find_index(jobs, job_id)
        entry = jobs[idx]

        if status is not None:
            entry["status"] = status
            if status == "running" and entry.get("started_at") is None:
                entry["started_at"] = datetime.now(UTC).isoformat()
            if status in _TERMINAL_STATUSES:
                entry["completed_at"] = datetime.now(UTC).isoformat()

        if progress is not None:
            entry["progress"] = progress

        if error is not None:
            entry["error"] = error

    def cancel(self, job_id: str) -> None:
        """Mark a job as cancelled and set its completion time."""
        jobs = _jobs_list()
        idx = _find_index(jobs, job_id)
        jobs[idx]["status"] = "cancelled"
        jobs[idx]["completed_at"] = datetime.now(UTC).isoformat()

    def get_active(self) -> list[JobEntry]:
        """Return queued + running jobs, sorted oldest started_at first."""
        jobs = _jobs_list()
        active = [_deserialize(j) for j in jobs if j["status"] in _ACTIVE_STATUSES]
        return sorted(active, key=lambda j: j.started_at or datetime.min.replace(tzinfo=UTC))

    def get_history(self, limit: int = 20) -> list[JobEntry]:
        """Return completed/failed/cancelled jobs, newest first."""
        jobs = _jobs_list()
        terminal = [_deserialize(j) for j in jobs if j["status"] in _TERMINAL_STATUSES]
        terminal.sort(
            key=lambda j: j.completed_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return terminal[:limit]

    def prune(self, max_age_days: int = 7) -> int:
        """Remove terminal entries older than *max_age_days*. Returns count removed."""
        jobs = _jobs_list()
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        keep: list[dict[str, Any]] = []
        removed = 0
        for j in jobs:
            if j["status"] in _ACTIVE_STATUSES:
                keep.append(j)
                continue
            completed_raw = j.get("completed_at")
            if completed_raw:
                completed = datetime.fromisoformat(completed_raw)
                if completed.tzinfo is None:
                    completed = completed.replace(tzinfo=UTC)
                if completed < cutoff:
                    removed += 1
                    continue
            keep.append(j)
        app.storage.user[USER_JOBS] = keep
        return removed
