"""Postgres backup and restore drill.

``pg_dump`` is invoked in custom format so a restore can be parallelised and
selective. ``--no-sync`` is deliberately *not* used: it returns before the dump
is on stable storage, which turns a backup into a promise rather than a file.

The restore drill restores into a scratch database and compares table row counts
against the source, so a backup nobody can restore fails loudly here rather than
during an incident. Timings are printed to feed the RTO/RPO figures the runbook
records.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sophia.config import Settings

SCRATCH_SUFFIX = "_restore_drill"
_ASYNC_DRIVER_PREFIX = "postgresql+asyncpg://"
_LIBPQ_PREFIX = "postgresql://"


def libpq_url(database_url: str) -> str:
    """Strip the SQLAlchemy driver so libpq tools accept the URL."""
    if database_url.startswith(_ASYNC_DRIVER_PREFIX):
        return _LIBPQ_PREFIX + database_url[len(_ASYNC_DRIVER_PREFIX) :]
    return database_url


def with_database(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def backup(database_url: str, output: Path) -> int:
    """Dump the database to ``output`` in custom format."""
    missing = _require_tools("pg_dump")
    if missing:
        return missing

    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = _run(
        [
            "pg_dump",
            "--format=custom",
            "--compress=9",
            "--no-owner",
            "--no-privileges",
            f"--file={output}",
            libpq_url(database_url),
        ]
    )
    if result != 0:
        return result

    elapsed = time.monotonic() - started
    size_mb = output.stat().st_size / 1024 / 1024
    print(f"backup ok: {output} ({size_mb:.1f} MiB) in {elapsed:.1f}s")
    return 0


def restore_drill(database_url: str, dump: Path) -> int:
    """Restore into a scratch database and compare row counts with the source."""
    missing = _require_tools("pg_restore", "psql")
    if missing:
        return missing

    if not dump.exists():
        print(f"dump not found: {dump}", file=sys.stderr)
        return 2

    source = database_name(database_url)
    scratch = f"{source}{SCRATCH_SUFFIX}"
    admin_url = libpq_url(with_database(database_url, "postgres"))

    started = time.monotonic()
    _psql(admin_url, f'DROP DATABASE IF EXISTS "{scratch}"')
    if _psql(admin_url, f'CREATE DATABASE "{scratch}"') != 0:
        return 1

    restored = _run(
        [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            f"--dbname={libpq_url(with_database(database_url, scratch))}",
            str(dump),
        ]
    )
    if restored != 0:
        return restored
    elapsed = time.monotonic() - started

    source_counts = _table_counts(libpq_url(database_url))
    scratch_counts = _table_counts(libpq_url(with_database(database_url, scratch)))
    _psql(admin_url, f'DROP DATABASE IF EXISTS "{scratch}"')

    if source_counts != scratch_counts:
        differing = sorted(
            name
            for name in set(source_counts) | set(scratch_counts)
            if source_counts.get(name) != scratch_counts.get(name)
        )
        print(f"restore MISMATCH in: {', '.join(differing)}", file=sys.stderr)
        return 1

    print(f"restore ok: {len(source_counts)} tables verified, RTO {elapsed:.1f}s")
    return 0


def _table_counts(url: str) -> dict[str, int]:
    query = (
        "SELECT relname, n_live_tup FROM pg_stat_user_tables "
        "WHERE schemaname = 'public' ORDER BY relname"
    )
    completed = subprocess.run(  # noqa: S603 — fixed argv, URL from settings
        ["psql", url, "-tAF", "\t", "-c", query],  # noqa: S607 — resolved from PATH in the image
        capture_output=True,
        text=True,
        check=False,
        env=_env(),
    )
    if completed.returncode != 0:
        print(completed.stderr.strip(), file=sys.stderr)
        return {}
    counts: dict[str, int] = {}
    for line in completed.stdout.splitlines():
        name, _, value = line.partition("\t")
        if name:
            counts[name] = int(value or 0)
    return counts


def _psql(url: str, statement: str) -> int:
    return _run(["psql", url, "-v", "ON_ERROR_STOP=1", "-c", statement])


def missing_tools(*tools: str) -> list[str]:
    """Return which libpq client binaries are absent from PATH."""
    return [tool for tool in tools if shutil.which(tool) is None]


def _require_tools(*tools: str) -> int:
    absent = missing_tools(*tools)
    if not absent:
        return 0
    print(
        f"missing PostgreSQL client tools: {', '.join(absent)} — "
        "install postgresql-client, or run this inside the backup container",
        file=sys.stderr,
    )
    return 2


def _run(argv: list[str]) -> int:
    completed = subprocess.run(argv, check=False, env=_env())  # noqa: S603 — fixed argv
    if completed.returncode != 0:
        print(f"command failed: {argv[0]}", file=sys.stderr)
    return completed.returncode


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("--output", type=Path, help="dump file to write (backup)")
    parser.add_argument("--input", type=Path, help="dump file to restore (restore)")
    parser.add_argument("--database-url", default="")
    args = parser.parse_args(argv)

    database_url = args.database_url or Settings().database_url

    if args.action == "backup":
        if args.output is None:
            parser.error("--output is required for backup")
        return backup(database_url, args.output)

    if args.input is None:
        parser.error("--input is required for restore")
    return restore_drill(database_url, args.input)


if __name__ == "__main__":
    raise SystemExit(main())
