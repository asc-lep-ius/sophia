"""One-shot SQLite-to-Postgres migration with row-count and checksum proof.

Modes:
  dry-run  read and checksum the source, write nothing
  import   copy every table, align sequences, then verify
  verify   compare an already-imported Postgres against the source

Exits non-zero when any table's row count or checksum disagrees, so the cutover
playbook can gate on it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sophia.config import Settings
from sophia.infra.alembic_runner import current_revision, head_revision
from sophia.infra.engine import create_engine
from sophia.infra.sqlite_import import (
    TransferReport,
    missing_tables,
    open_sqlite,
    transfer,
    verify,
)

MODES = ("dry-run", "import", "verify")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True, help="source SQLite database")
    parser.add_argument("--database-url", default="", help="target Postgres URL")
    parser.add_argument("--mode", choices=MODES, default="dry-run")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)

    if not args.sqlite.exists():
        print(f"source database not found: {args.sqlite}", file=sys.stderr)
        return 2

    database_url = args.database_url or Settings().database_url
    return asyncio.run(_run(args.sqlite, database_url, args.mode, args.batch_size))


async def _run(sqlite_path: Path, database_url: str, mode: str, batch_size: int) -> int:
    connection = open_sqlite(sqlite_path)
    engine = create_engine(database_url)
    try:
        unmodelled = missing_tables(connection)
        if unmodelled:
            print(
                "source tables absent from the Postgres schema: " + ", ".join(unmodelled),
                file=sys.stderr,
            )
            return 2

        if mode != "dry-run" and not await _schema_ready(engine, database_url):
            print(
                "target is not migrated to head — run 'alembic upgrade head' first",
                file=sys.stderr,
            )
            return 2

        report = (
            await verify(connection, engine)
            if mode == "verify"
            else await transfer(
                connection,
                engine,
                dry_run=mode == "dry-run",
                batch_size=batch_size,
            )
        )
    finally:
        await engine.dispose()
        connection.close()

    _print_report(report, mode)
    return 0 if report.ok else 1


async def _schema_ready(engine: object, database_url: str) -> bool:
    return await current_revision(engine) == head_revision(database_url)  # pyright: ignore[reportArgumentType]


def _print_report(report: TransferReport, mode: str) -> None:
    width = max((len(table.table) for table in report.tables), default=0)
    for table in report.tables:
        marker = "ok " if table.ok else "FAIL"
        print(
            f"{marker} {table.table.ljust(width)}  "
            f"rows {table.source_rows}->{table.target_rows}  "
            f"checksum {table.source_checksum[:12]}"
            f"{'' if table.checksums_match else ' != ' + table.target_checksum[:12]}"
        )

    print(f"\n{mode}: {len(report.tables)} tables, {report.total_rows} source rows")
    if report.failures:
        names = ", ".join(table.table for table in report.failures)
        print(f"MISMATCH in: {names}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
