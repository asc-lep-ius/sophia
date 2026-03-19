"""Internal run-job command for executing scheduled jobs."""

from __future__ import annotations

import cyclopts
import structlog

log = structlog.get_logger()


def register_run_job(root_app: cyclopts.App) -> None:
    """Register the hidden _run-job command on the root app."""

    @root_app.command(name="_run-job", group=cyclopts.Group("Internal", show=False))
    async def run_job(job_id: str) -> None:  # pyright: ignore[reportUnusedFunction]
        """Internal: Execute a scheduled job with auto-relogin. Not for direct use."""
        import shlex

        from sophia.config import Settings
        from sophia.domain.models import JobStatus
        from sophia.infra.persistence import connect_db, run_migrations
        from sophia.infra.scheduler import create_scheduler
        from sophia.services.job_runner import ensure_valid_session

        settings = Settings()
        db = await connect_db(settings.db_path)
        scheduler = None
        try:
            await run_migrations(db)
            scheduler = create_scheduler(db)

            job = await scheduler.get_job(job_id)
            if job is None:
                log.error("job_not_found", job_id=job_id)
                raise SystemExit(1)

            await scheduler.update_status(job_id, JobStatus.RUNNING)

            session_ok = await ensure_valid_session(
                settings.config_dir, settings.tuwel_host, settings.tiss_host
            )
            if not session_ok:
                log.error("job_failed_no_session", job_id=job_id)
                await scheduler.update_status(job_id, JobStatus.FAILED)
                raise SystemExit(1)

            command_tokens = shlex.split(job.command)
            log.info("job_executing", job_id=job_id, command=job.command)

            try:
                root_app(command_tokens)
            except SystemExit as exc:
                if exc.code and exc.code != 0:
                    await scheduler.update_status(job_id, JobStatus.FAILED)
                    raise

            await scheduler.update_status(job_id, JobStatus.COMPLETED)
            log.info("job_completed", job_id=job_id)
        except SystemExit:
            raise
        except Exception:
            log.error("job_failed", job_id=job_id, exc_info=True)
            if scheduler is not None:
                try:
                    await scheduler.update_status(job_id, JobStatus.FAILED)
                except Exception:
                    log.error("job_status_update_failed", job_id=job_id, exc_info=True)
            raise SystemExit(1) from None
        finally:
            await db.close()
