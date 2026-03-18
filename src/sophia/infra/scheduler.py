"""Cross-platform job scheduler using OS-native scheduling APIs.

- Linux: systemd-run --user (transient timer units)
- macOS: launchd via plist files in ~/Library/LaunchAgents/
- Windows: schtasks /Create /SC ONCE /Z (auto-delete after run)
"""

from __future__ import annotations

import abc
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

from sophia.domain.models import JobStatus, ScheduledJob

log = structlog.get_logger()


class SchedulerError(Exception):
    """Raised when a scheduling operation fails."""


class Scheduler(abc.ABC):
    """Abstract scheduler interface — one implementation per platform."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def schedule(
        self,
        command: str,
        scheduled_for: datetime,
        *,
        description: str = "",
    ) -> ScheduledJob:
        """Schedule a sophia command to run at the specified time.

        Args:
            command: Full CLI command (without 'sophia' prefix),
                     e.g. "register go 186.813 --watch"
            scheduled_for: When to run (must be in the future)
            description: Human-readable label for the job
        """
        if scheduled_for <= datetime.now(UTC):
            msg = "Cannot schedule a job in the past"
            raise SchedulerError(msg)

        job_id = self._generate_job_id()
        now = datetime.now(UTC)

        sophia_exe = shutil.which("sophia") or f"{sys.executable} -m sophia"
        full_command = f"{sophia_exe} _run-job {job_id}"

        job = ScheduledJob(
            job_id=job_id,
            command=command,
            scheduled_for=scheduled_for.isoformat(),
            created_at=now.isoformat(),
            status=JobStatus.PENDING,
            description=description,
        )
        await self._persist_job(job)

        try:
            self._create_os_job(job_id, full_command, scheduled_for)
        except SchedulerError:
            await self._update_status(job_id, JobStatus.FAILED)
            raise

        log.info("job_scheduled", job_id=job_id, scheduled_for=scheduled_for.isoformat())
        return job

    async def cancel(self, job_id: str) -> None:
        """Cancel a scheduled job."""
        self._cancel_os_job(job_id)
        await self._update_status(job_id, JobStatus.CANCELLED)
        log.info("job_cancelled", job_id=job_id)

    async def list_jobs(self) -> list[ScheduledJob]:
        """Return all tracked jobs ordered by scheduled time."""
        cursor = await self._db.execute(
            "SELECT job_id, command, scheduled_for, created_at, status, description "
            "FROM scheduled_jobs ORDER BY scheduled_for"
        )
        rows = await cursor.fetchall()
        return [
            ScheduledJob(
                job_id=r[0],
                command=r[1],
                scheduled_for=r[2],
                created_at=r[3],
                status=JobStatus(r[4]),
                description=r[5],
            )
            for r in rows
        ]

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        """Update a job's status (called by the job runner)."""
        await self._update_status(job_id, status)

    async def get_job(self, job_id: str) -> ScheduledJob | None:
        """Look up a single job by ID."""
        cursor = await self._db.execute(
            "SELECT job_id, command, scheduled_for, created_at, status, description "
            "FROM scheduled_jobs WHERE job_id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ScheduledJob(
            job_id=row[0],
            command=row[1],
            scheduled_for=row[2],
            created_at=row[3],
            status=JobStatus(row[4]),
            description=row[5],
        )

    @abc.abstractmethod
    def _create_os_job(self, job_id: str, command: str, scheduled_for: datetime) -> None:
        """Platform-specific: create the OS-level scheduled task."""

    @abc.abstractmethod
    def _cancel_os_job(self, job_id: str) -> None:
        """Platform-specific: remove the OS-level scheduled task."""

    def _generate_job_id(self) -> str:
        return f"sophia-{uuid.uuid4().hex[:8]}"

    async def _persist_job(self, job: ScheduledJob) -> None:
        await self._db.execute(
            "INSERT INTO scheduled_jobs "
            "(job_id, command, scheduled_for, created_at, status, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                job.job_id,
                job.command,
                job.scheduled_for,
                job.created_at,
                job.status.value,
                job.description,
            ),
        )
        await self._db.commit()

    async def _update_status(self, job_id: str, status: JobStatus) -> None:
        await self._db.execute(
            "UPDATE scheduled_jobs SET status = ? WHERE job_id = ?",
            (status.value, job_id),
        )
        await self._db.commit()


# ---------------------------------------------------------------------------
# Platform backends
# ---------------------------------------------------------------------------


class _LinuxScheduler(Scheduler):
    """Uses systemd-run --user for transient timer units."""

    def _create_os_job(self, job_id: str, command: str, scheduled_for: datetime) -> None:
        timestamp = scheduled_for.strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    f"--unit={job_id}",
                    f"--on-calendar={timestamp}",
                    "--",
                    *shlex.split(command),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise SchedulerError(f"systemd-run failed: {exc.stderr}") from exc
        except FileNotFoundError:
            raise SchedulerError("systemd-run not found — is systemd available?") from None

    def _cancel_os_job(self, job_id: str) -> None:
        for suffix in [".timer", ".service"]:
            subprocess.run(
                ["systemctl", "--user", "stop", f"{job_id}{suffix}"],
                capture_output=True,
            )


class _MacOSScheduler(Scheduler):
    """Uses launchd via plist files in ~/Library/LaunchAgents/."""

    _AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

    def _plist_path(self, job_id: str) -> Path:
        return self._AGENTS_DIR / f"{job_id}.plist"

    def _create_os_job(self, job_id: str, command: str, scheduled_for: datetime) -> None:
        import plistlib

        self._AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        parts = shlex.split(command)
        plist = {
            "Label": job_id,
            "ProgramArguments": parts,
            "StartCalendarInterval": {
                "Year": scheduled_for.year,
                "Month": scheduled_for.month,
                "Day": scheduled_for.day,
                "Hour": scheduled_for.hour,
                "Minute": scheduled_for.minute,
            },
            "RunAtLoad": False,
        }
        plist_path = self._plist_path(job_id)
        with plist_path.open("wb") as f:
            plistlib.dump(plist, f)

        try:
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            plist_path.unlink(missing_ok=True)
            raise SchedulerError(f"launchctl load failed: {exc.stderr}") from exc

    def _cancel_os_job(self, job_id: str) -> None:
        plist_path = self._plist_path(job_id)
        if plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
            )
            plist_path.unlink(missing_ok=True)


class _WindowsScheduler(Scheduler):
    """Uses schtasks for Windows Task Scheduler."""

    def _create_os_job(self, job_id: str, command: str, scheduled_for: datetime) -> None:
        start_time = scheduled_for.strftime("%H:%M")
        start_date = scheduled_for.strftime("%m/%d/%Y")
        try:
            subprocess.run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    job_id,
                    "/TR",
                    command,  # schtasks /TR expects a single string, not tokenized args
                    "/SC",
                    "ONCE",
                    "/ST",
                    start_time,
                    "/SD",
                    start_date,
                    "/Z",
                    "/F",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise SchedulerError(f"schtasks failed: {exc.stderr}") from exc
        except FileNotFoundError:
            raise SchedulerError("schtasks not found — are you on Windows?") from None

    def _cancel_os_job(self, job_id: str) -> None:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", job_id, "/F"],
            capture_output=True,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_scheduler(db: aiosqlite.Connection) -> Scheduler:
    """Create the appropriate scheduler for the current platform."""
    import platform

    system = platform.system()
    if system == "Linux":
        return _LinuxScheduler(db)
    if system == "Darwin":
        return _MacOSScheduler(db)
    if system == "Windows":
        return _WindowsScheduler(db)
    raise SchedulerError(f"Unsupported platform: {system}")
