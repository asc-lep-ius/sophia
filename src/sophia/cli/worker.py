"""The processing worker — `sophia worker run` is what the worker container runs."""

from __future__ import annotations

from typing import Annotated

import cyclopts

app = cyclopts.App(
    name="worker",
    help=(
        "The processing worker (#128).\n"
        "\n"
        " run    — poll for queued jobs and process them on the GPU\n"
        " stage  — internal: one stage group of one module, started by `run` in a child process"
    ),
)


@app.command(name="run")
async def worker_run(
    *,
    poll_interval: Annotated[
        float, cyclopts.Parameter(help="Seconds between polls of the job queue.")
    ] = 5.0,
    once: Annotated[
        bool, cyclopts.Parameter(help="Process what is queued now, then exit.")
    ] = False,
) -> None:
    """Poll the job queue and process each job's lectures."""
    from sophia.infra.logging import setup_logging
    from sophia.worker.runner import run_worker

    setup_logging(json_logs=True, service_name="worker")
    await run_worker(poll_interval_s=poll_interval, stop_when_idle=once)


@app.command(name="stage")
async def worker_stage(
    group: Annotated[str, cyclopts.Parameter(help="media or knowledge")],
    module_id: int,
    *,
    course_id: Annotated[int, cyclopts.Parameter(help="The course the module's topics belong to.")],
    job_id: Annotated[int, cyclopts.Parameter(help="The job whose progress to record.")],
) -> None:
    """Internal: run one stage group of one module in this process."""
    from sophia.infra.logging import setup_logging
    from sophia.worker.stage import run_stage_group

    setup_logging(json_logs=True, service_name="worker-stage")
    await run_stage_group(group, module_id, course_id=course_id, job_id=job_id)
