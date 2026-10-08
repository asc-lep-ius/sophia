"""Soak the TU Wien session keepalive (#124): watch TUWEL's idle clock without touching it.

Run it beside a long-lived API, whose lifespan runs the keepalive, for at
least 24 hours:

    uv run python scripts/soak_upstream_session.py --hours 24 | tee soak.csv

Every --every seconds it reads ``core_session_time_remaining`` with
``nosessionupdate``, which TUWEL does not count as activity, for the session
the config directory holds — re-read each time, so a renewal by the keepalive
is followed rather than mistaken for a death. Each sample is one CSV line on
stdout; the verdict goes to stderr.

Exit 0 when TUWEL's idle time never fell below 28 800 s minus the keepalive
interval (and --grace for the ping's own latency), no sample found the session
dead, and TISS still answers at the end. Exit 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from sophia.adapters.auth import load_session, load_tiss_session, session_path, tiss_session_path
from sophia.adapters.moodle import MoodleAdapter
from sophia.adapters.tiss_registration import TissRegistrationAdapter
from sophia.config import Settings
from sophia.domain.errors import AuthError
from sophia.infra.http import http_session
from sophia.services.tiss_registration import current_semester

# Measured on 2026-10-08: a fresh session read 28 800 s, falling 1 s per second idle.
TUWEL_IDLE_TIMEOUT_S = 28_800


async def _tuwel_remaining(settings: Settings) -> int:
    creds = load_session(session_path(settings.config_dir))
    if creds is None:
        raise AuthError("no stored TUWEL session")
    async with http_session() as http:
        http.cookies.set(
            creds.cookie_name,
            creds.moodle_session,
            domain=urlparse(settings.tuwel_host).hostname or "",
        )
        adapter = MoodleAdapter(
            http=http,
            sesskey=creds.sesskey,
            moodle_session=creds.moodle_session,
            host=settings.tuwel_host,
            cookie_name=creds.cookie_name,
        )
        return await adapter.session_time_remaining()


async def _tiss_answers(settings: Settings) -> bool:
    creds = load_tiss_session(tiss_session_path(settings.config_dir))
    if creds is None:
        return False
    async with http_session() as http:
        adapter = TissRegistrationAdapter(http=http, credentials=creds, host=settings.tiss_host)
        try:
            await adapter.get_favorites(current_semester())
        except AuthError:
            return False
    return True


async def _soak(hours: float, every: float, interval: float, grace: float) -> int:
    settings = Settings()
    floor = TUWEL_IDLE_TIMEOUT_S - interval - grace
    deadline = time.monotonic() + hours * 3600
    lowest: int | None = None
    dead = 0

    print("utc,remaining_s", flush=True)
    while True:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            remaining = await _tuwel_remaining(settings)
        except AuthError:
            dead += 1
            print(f"{now},dead", flush=True)
        except httpx.HTTPError as exc:
            print(f"{now},unreachable:{type(exc).__name__}", flush=True)
        else:
            lowest = remaining if lowest is None else min(lowest, remaining)
            print(f"{now},{remaining}", flush=True)
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(every)

    tiss_ok = await _tiss_answers(settings)
    passed = lowest is not None and lowest >= floor and dead == 0 and tiss_ok
    print(
        f"{'PASS' if passed else 'FAIL'}: lowest TUWEL idle time left {lowest} s "
        f"(floor {floor:.0f} s), {dead} dead sample(s), TISS "
        f"{'answers' if tiss_ok else 'does not answer'}",
        file=sys.stderr,
    )
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24.0, help="how long to soak")
    parser.add_argument("--every", type=float, default=60.0, help="seconds between samples")
    parser.add_argument(
        "--interval",
        type=float,
        default=300.0,
        help="the API's SOPHIA_SESSION_KEEPALIVE_INTERVAL, in seconds",
    )
    parser.add_argument(
        "--grace", type=float, default=60.0, help="seconds allowed for the ping's own latency"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_soak(args.hours, args.every, args.interval, args.grace)))


if __name__ == "__main__":
    main()
