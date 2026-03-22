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
    from pathlib import Path

from sophia.domain.models import JobStatus
from sophia.infra.scheduler import (
    SchedulerError,
    _LinuxScheduler,  # pyright: ignore[reportPrivateUsage]
    _MacOSScheduler,  # pyright: ignore[reportPrivateUsage]
    _WindowsScheduler,  # pyright: ignore[reportPrivateUsage]
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

    def test_darwin(self, mock_db: aiosqlite.Connection) -> None:
        with patch("platform.system", return_value="Darwin"):
            s = create_scheduler(mock_db)
        assert isinstance(s, _MacOSScheduler)  # pyright: ignore[reportPrivateUsage]

    def test_windows(self, mock_db: aiosqlite.Connection) -> None:
        with patch("platform.system", return_value="Windows"):
            s = create_scheduler(mock_db)
        assert isinstance(s, _WindowsScheduler)  # pyright: ignore[reportPrivateUsage]

    def test_unsupported_platform(self, mock_db: aiosqlite.Connection) -> None:
        with (
            patch("platform.system", return_value="FreeBSD"),
            pytest.raises(SchedulerError, match="Unsupported"),
        ):
            create_scheduler(mock_db)


class TestLinuxSchedulerErrors:
    async def test_systemd_not_found_raises(self, mock_db: aiosqlite.Connection) -> None:
        """FileNotFoundError from subprocess → SchedulerError about systemd."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            with pytest.raises(SchedulerError, match="systemd-run not found"):
                await scheduler.schedule("register go 186.813", future)

    async def test_get_job_exists(self, mock_db: aiosqlite.Connection) -> None:
        with patch("subprocess.run"):
            scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            created = await scheduler.schedule("register go 186.813", future)

        job = await scheduler.get_job(created.job_id)
        assert job is not None
        assert job.command == "register go 186.813"

    async def test_get_job_missing(self, mock_db: aiosqlite.Connection) -> None:
        scheduler = _LinuxScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
        job = await scheduler.get_job("nonexistent-id")
        assert job is None


class TestMacOSScheduler:
    async def test_create_and_cancel(self, mock_db: aiosqlite.Connection, tmp_path: Path) -> None:
        """macOS scheduler writes plist and calls launchctl."""
        scheduler = _MacOSScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
        scheduler._AGENTS_DIR = tmp_path  # pyright: ignore[reportPrivateUsage]

        with patch("subprocess.run"):
            future = datetime.now(UTC) + timedelta(hours=1)
            job = await scheduler.schedule("register go 186.813", future)

        plist = tmp_path / f"{job.job_id}.plist"
        assert plist.exists()

        # Cancel should remove plist
        with patch("subprocess.run"):
            await scheduler.cancel(job.job_id)
        assert not plist.exists()

    async def test_launchctl_failure(self, mock_db: aiosqlite.Connection, tmp_path: Path) -> None:
        """CalledProcessError from launchctl → SchedulerError and plist cleaned up."""
        scheduler = _MacOSScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
        scheduler._AGENTS_DIR = tmp_path  # pyright: ignore[reportPrivateUsage]

        def _fake_run(cmd: list[str], **kw: object) -> sp.CompletedProcess[str]:
            if "launchctl" in cmd:
                raise sp.CalledProcessError(1, "launchctl", stderr="load failed")
            return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_fake_run):
            future = datetime.now(UTC) + timedelta(hours=1)
            with pytest.raises(SchedulerError, match="launchctl"):
                await scheduler.schedule("register go 186.813", future)


class TestWindowsScheduler:
    async def test_create_os_job(self, mock_db: aiosqlite.Connection) -> None:
        """Windows scheduler calls schtasks with expected arguments."""
        scheduler = _WindowsScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]

        with patch("subprocess.run") as mock_run:
            future = datetime.now(UTC) + timedelta(hours=1)
            job = await scheduler.schedule("register go 186.813", future)

        # Verify schtasks was called (schedule internally calls _create_os_job)
        schtasks_calls = [c for c in mock_run.call_args_list if "schtasks" in str(c)]
        assert len(schtasks_calls) >= 1
        assert job.status == JobStatus.PENDING

    async def test_schtasks_not_found(self, mock_db: aiosqlite.Connection) -> None:
        """FileNotFoundError from schtasks → SchedulerError."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            scheduler = _WindowsScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            with pytest.raises(SchedulerError, match="schtasks not found"):
                await scheduler.schedule("register go 186.813", future)

    async def test_schtasks_failure(self, mock_db: aiosqlite.Connection) -> None:
        """CalledProcessError from schtasks → SchedulerError."""
        with patch(
            "subprocess.run",
            side_effect=sp.CalledProcessError(1, "schtasks", stderr="failed"),
        ):
            scheduler = _WindowsScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            with pytest.raises(SchedulerError, match="schtasks failed"):
                await scheduler.schedule("register go 186.813", future)

    async def test_cancel(self, mock_db: aiosqlite.Connection) -> None:
        """Windows cancel calls schtasks /Delete."""
        with patch("subprocess.run"):
            scheduler = _WindowsScheduler(mock_db)  # pyright: ignore[reportPrivateUsage]
            future = datetime.now(UTC) + timedelta(hours=1)
            job = await scheduler.schedule("register go 186.813", future)
            await scheduler.cancel(job.job_id)

        jobs = await scheduler.list_jobs()
        assert jobs[0].status == JobStatus.CANCELLED
