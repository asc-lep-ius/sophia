"""Processing a learning path from the browser: the routes behind Process (#128).

Against the real routes and Postgres: what is under test is the queue the
worker reads, the refusals a learner sees, and the settings a second run
honours. Only the worker is absent — its heartbeat row is written by hand,
which is exactly what the API reads to decide whether it can refuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import insert, select

from sophia.api.routers import content_sources as content_sources_router
from sophia.infra.schema import ingestion_jobs, learning_path_settings, lecture_modules
from sophia.services.ingestion_jobs import NO_WORKER_REASON, claim_next_job, finish_job, heartbeat

from ._db_harness import DbHarness, db_harness, learning_path_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from sophia.services.hermes_catalog import DiscoveredLectureModule

pytestmark = pytest.mark.postgres

EP1 = 82774
GDS = 83629
STATUS = f"/api/learning-paths/{EP1}/ingestion"
SETTINGS = f"/api/learning-paths/{EP1}/ingestion/settings"


async def _seed_course(session: AsyncSession) -> None:
    for module_id in (3022060, 3022498):
        await session.execute(
            insert(lecture_modules).values(
                module_id=module_id,
                course_id=str(EP1),
                course_name="185.A91 Einführung in die Programmierung 1",
            )
        )


async def _worker(session: AsyncSession, *, capable: bool = True, reason: str = "") -> None:
    await heartbeat(
        session,
        "hephaestus:1",
        hostname="hephaestus",
        capable=capable,
        reason=reason,
        gpu_name="NVIDIA GeForce GTX 1070",
    )


async def _status(harness: DbHarness) -> dict[str, Any]:
    response = await harness.client.get(STATUS)
    assert response.status_code == 200, response.text
    return response.json()


def _harness(engine: AsyncEngine):
    return db_harness(engine, tenant=learning_path_tenant(EP1))


async def test_process_queues_a_job_subscribes_the_course_and_shows_it_after_a_reload(
    clean_engine: AsyncEngine,
) -> None:
    """Scenario 1's start, and "processing outlives the page"."""
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
            await _worker(session)
        await harness.login()

        before = await _status(harness)
        started = await harness.client.post(STATUS, headers=harness.csrf_headers())
        after = await _status(harness)

    assert before["job"] is None
    assert before["settings"] == {
        "learning_path_id": EP1,
        "subscribed": False,
        "transcription_language": None,
    }
    assert before["worker"] == {
        "available": True,
        "reason": "",
        "gpu_name": "NVIDIA GeForce GTX 1070",
    }
    assert [source["id"] for source in before["sources"]] == [3022060, 3022498]

    assert started.status_code == 202, started.text
    job = started.json()
    assert (job["learning_path_id"], job["state"], job["requested_by"]) == (
        EP1,
        "queued",
        "student",
    )
    # A fresh GET, as a reloaded page makes, shows the same job and the subscription.
    assert after["job"]["id"] == job["id"]
    assert after["job"]["state"] == "queued"
    assert after["settings"]["subscribed"] is True


async def test_process_is_refused_when_no_worker_can_process(clean_engine: AsyncEngine) -> None:
    """Scenario: no GPU — refused with that reason, never a silent failure."""
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
        await harness.login()
        refused_no_worker = await harness.client.post(STATUS, headers=harness.csrf_headers())

        async with harness.seed() as session:
            await _worker(
                session, capable=False, reason="No usable NVIDIA GPU: nvidia-smi found none"
            )
        shown = await _status(harness)
        refused_no_gpu = await harness.client.post(STATUS, headers=harness.csrf_headers())

        async with harness.seed() as session:
            jobs = (await session.execute(select(ingestion_jobs))).all()

    assert refused_no_worker.status_code == 503
    assert refused_no_worker.json() == {
        "detail": {"code": "ingestion.unavailable", "params": {"reason": NO_WORKER_REASON}}
    }
    assert shown["worker"] == {
        "available": False,
        "reason": "No usable NVIDIA GPU: nvidia-smi found none",
        "gpu_name": "",
    }
    assert refused_no_gpu.status_code == 503
    assert refused_no_gpu.json()["detail"]["params"] == {
        "reason": "No usable NVIDIA GPU: nvidia-smi found none"
    }
    assert jobs == []


async def test_a_second_process_says_it_is_already_running(clean_engine: AsyncEngine) -> None:
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
            await _worker(session)
        await harness.login()
        first = await harness.client.post(STATUS, headers=harness.csrf_headers())
        async with harness.seed() as session:
            claimed = await claim_next_job(session, "hephaestus:1")
        second = await harness.client.post(STATUS, headers=harness.csrf_headers())
        shown = await _status(harness)

    assert first.status_code == 202
    assert claimed is not None
    assert second.status_code == 409
    assert second.json() == {
        "detail": {"code": "ingestion.already_running", "params": {"job_id": claimed.id}}
    }
    assert shown["job"]["state"] == "processing"


async def test_a_failed_job_is_shown_with_its_reason_and_can_be_retried(
    clean_engine: AsyncEngine,
) -> None:
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
            await _worker(session)
        await harness.login()
        first = await harness.client.post(STATUS, headers=harness.csrf_headers())
        async with harness.seed() as session:
            claimed = await claim_next_job(session, "hephaestus:1")
            assert claimed is not None
            await finish_job(session, claimed.id, error="Download and transcription failed: 401")
        failed = await _status(harness)
        retried = await harness.client.post(STATUS, headers=harness.csrf_headers())

    assert first.status_code == 202
    assert failed["job"]["state"] == "failed"
    assert failed["job"]["error"] == "Download and transcription failed: 401"
    assert retried.status_code == 202
    assert retried.json()["id"] != first.json()["id"]


async def test_settings_stop_following_and_set_the_language(clean_engine: AsyncEngine) -> None:
    """Scenarios: unsubscribe, and the lecture language set on the course."""
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
            await _worker(session)
        await harness.login()
        await harness.client.post(STATUS, headers=harness.csrf_headers())
        with_language = await harness.client.put(
            SETTINGS,
            json={"subscribed": True, "transcription_language": "en"},
            headers=harness.csrf_headers(),
        )
        unfollowed = await harness.client.put(
            SETTINGS,
            json={"subscribed": False, "transcription_language": "en"},
            headers=harness.csrf_headers(),
        )
        bad_language = await harness.client.put(
            SETTINGS,
            json={"subscribed": True, "transcription_language": "english"},
            headers=harness.csrf_headers(),
        )
        shown = await _status(harness)
        async with harness.seed() as session:
            row = (
                await session.execute(
                    select(learning_path_settings).where(learning_path_settings.c.course_id == EP1)
                )
            ).one()

    assert with_language.status_code == 200
    assert with_language.json() == {
        "learning_path_id": EP1,
        "subscribed": True,
        "transcription_language": "en",
    }
    assert unfollowed.status_code == 200
    assert bad_language.status_code == 422
    assert shown["settings"] == {
        "learning_path_id": EP1,
        "subscribed": False,
        "transcription_language": "en",
    }
    # The job already queued stays; only the subscription changed.
    assert shown["job"]["state"] == "queued"
    assert (row.ingestion_subscribed, row.transcription_language) == (False, "en")


async def test_another_learning_path_cannot_read_or_start_processing(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(GDS)) as harness:
        await harness.login()
        read = await harness.client.get(STATUS)
        started = await harness.client.post(STATUS, headers=harness.csrf_headers())

    assert read.status_code == 403
    assert started.status_code == 403


async def test_a_scan_queues_the_subscribed_course(
    clean_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: new recordings follow automatically, on scan."""

    async def fake_discover(_app: object, session: AsyncSession) -> list[DiscoveredLectureModule]:
        return []

    monkeypatch.setattr(content_sources_router, "discover_lecture_modules", fake_discover)
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
            await _worker(session)
        await harness.login()
        await harness.client.put(
            SETTINGS,
            json={"subscribed": True, "transcription_language": None},
            headers=harness.csrf_headers(),
        )
        scanned = await harness.client.post(
            "/api/content-sources/discover", headers=harness.csrf_headers()
        )
        shown = await _status(harness)

    assert scanned.status_code == 200
    assert shown["job"] is not None
    assert (shown["job"]["state"], shown["job"]["requested_by"]) == ("queued", "scan")
