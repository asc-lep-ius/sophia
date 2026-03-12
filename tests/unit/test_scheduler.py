"""Tests for the cross-platform job scheduler."""

from __future__ import annotations

import subprocess as sp
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import aiosqlite
import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from sophia.domain.models import JobStatus
from sophia.infra.scheduler import (
    SchedulerError,
    _LinuxScheduler,  # pyright: ignore[reportPrivateUsage]
    create_scheduler,
)


@pytest.fixture
async def mock_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """In-memory SQLite via aiosqlite for testing."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE scheduled_jobs (
            job_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            description TEXT NOT NULL DEFAULT ''
        )
    """)
    await db.commit()
    yield db
    await db.close()


class TestScheduler:
    async def test_schedule_creates_job(self, mock_db: aiosqlite.Connection) -> None:
        with patch("subprocess.run") as mock_run:
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            job = await scheduler.schedule(
                "register go 186.813 --watch",
                future,
                description="Register for course",
            )

        assert job.command == "register go 186.813 --watch"
        assert job.status == JobStatus.PENDING
        assert job.description == "Register for course"
        assert job.job_id.startswith("sophia-")
        mock_run.assert_called_once()

    async def test_schedule_past_time_raises(self, mock_db: aiosqlite.Connection) -> None:
        scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
        past = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(SchedulerError, match="past"):
            await scheduler.schedule("register go 186.813", past)

    async def test_list_jobs_returns_persisted(self, mock_db: aiosqlite.Connection) -> None:
        with patch("subprocess.run"):
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            await scheduler.schedule("register go 186.813", future)
            await scheduler.schedule("register go 185.123", future + timedelta(hours=1))

        jobs = await scheduler.list_jobs()
        assert len(jobs) == 2
        assert jobs[0].command == "register go 186.813"

    async def test_cancel_updates_status(self, mock_db: aiosqlite.Connection) -> None:
        with patch("subprocess.run"):
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            job = await scheduler.schedule("register go 186.813", future)
            await scheduler.cancel(job.job_id)

        jobs = await scheduler.list_jobs()
        assert jobs[0].status == JobStatus.CANCELLED

    async def test_systemd_run_failure_raises(self, mock_db: aiosqlite.Connection) -> None:
        with patch(
            "subprocess.run",
            side_effect=sp.CalledProcessError(1, "systemd-run", stderr="fail"),
        ):
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            with pytest.raises(SchedulerError, match="systemd-run failed"):
                await scheduler.schedule("register go 186.813", future)

        # Job persisted but marked failed when OS scheduling fails
        jobs = await scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].status == JobStatus.FAILED

    async def test_update_status(self, mock_db: aiosqlite.Connection) -> None:
        with patch("subprocess.run"):
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            job = await scheduler.schedule("register go 186.813", future)
            await scheduler.update_status(job.job_id, JobStatus.RUNNING)

        jobs = await scheduler.list_jobs()
        assert jobs[0].status == JobStatus.RUNNING


class TestCreateScheduler:
    def test_linux(self, mock_db: aiosqlite.Connection) -> None:
        with patch("platform.system", return_value="Linux"):
            s = create_scheduler(mock_db)
        assert isinstance(s, _LinuxScheduler)  # pyright: ignore[reportPrivateUsage]

    def test_unsupported_platform(self, mock_db: aiosqlite.Connection) -> None:
        with (
            patch("platform.system", return_value="FreeBSD"),
            pytest.raises(SchedulerError, match="Unsupported"),
        ):
            create_scheduler(mock_db)
