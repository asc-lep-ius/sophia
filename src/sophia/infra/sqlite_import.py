"""One-shot SQLite-to-Postgres transfer with verification.

Row counts alone are not proof that a migration worked: a column that silently
became NULL, a boolean that arrived as the integer 1, or a timestamp that lost
its offset all preserve the count. So every table is also checksummed, and the
checksum is computed from a canonical Python representation on *both* sides
rather than from engine-specific SQL, which is the only way the two numbers mean
the same thing.

SQLite's dynamic typing means the source values need coercing to the types the
Postgres columns declare. Two conversions carry a judgement worth stating:

* Naive timestamps are read as UTC. SQLite's ``CURRENT_TIMESTAMP`` emits UTC
  without an offset, and every timestamp the application writes itself is
  already UTC-aware, so this is a restatement of what the data means rather
  than a guess about it.
* Integers 0 and 1 in boolean columns become ``false``/``true``. SQLite has no
  boolean type and stored them as integers all along.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy import Boolean, Float, Integer, insert, select, text

from sophia.infra.schema import metadata

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from sqlalchemy import Column, Table
    from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()

NULL_TOKEN = "\\N"
FIELD_SEPARATOR = "\x1f"
ROW_SEPARATOR = "\x1e"
DEFAULT_BATCH_SIZE = 500

# SQLite bookkeeping that has no Postgres counterpart: the numbered-migration
# ledger is replaced by alembic_version, and sequences are Postgres-native.
SKIPPED_SOURCE_TABLES = frozenset({"schema_version", "sqlite_sequence"})


@dataclass(frozen=True, slots=True)
class TableReport:
    """Per-table outcome of a transfer or verification pass."""

    table: str
    source_rows: int
    target_rows: int
    source_checksum: str
    target_checksum: str

    @property
    def rows_match(self) -> bool:
        return self.source_rows == self.target_rows

    @property
    def checksums_match(self) -> bool:
        return self.source_checksum == self.target_checksum

    @property
    def ok(self) -> bool:
        return self.rows_match and self.checksums_match


@dataclass(frozen=True, slots=True)
class TransferReport:
    """Outcome across every table."""

    tables: tuple[TableReport, ...]
    dry_run: bool

    @property
    def ok(self) -> bool:
        return all(report.ok for report in self.tables)

    @property
    def failures(self) -> tuple[TableReport, ...]:
        return tuple(report for report in self.tables if not report.ok)

    @property
    def total_rows(self) -> int:
        return sum(report.source_rows for report in self.tables)


def open_sqlite(path: Path) -> sqlite3.Connection:
    """Open the source database read-only so a botched run cannot damage it."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def source_tables(connection: sqlite3.Connection) -> list[str]:
    """Return the source tables that have a Postgres counterpart."""
    cursor = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    present = {str(row[0]) for row in cursor.fetchall()} - SKIPPED_SOURCE_TABLES
    return [table.name for table in metadata.sorted_tables if table.name in present]


def missing_tables(connection: sqlite3.Connection) -> list[str]:
    """Return source tables the Postgres schema does not model.

    Reported rather than ignored: an unmodelled table is data the migration
    would drop on the floor without ever failing a row count.
    """
    cursor = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    present = {str(row[0]) for row in cursor.fetchall()} - SKIPPED_SOURCE_TABLES
    return sorted(present - set(metadata.tables))


def transferable_columns(connection: sqlite3.Connection, table: Table) -> list[Column[object]]:
    """Columns a table has on both sides.

    A revision can add a Postgres-only column to a table this tool also
    transfers (a ``session_id``/idempotency-key column, say) — the legacy
    SQLite source never had it and never will. Such columns get Postgres's own
    default on insert rather than being read from a source that cannot supply
    them, and are excluded from the checksum for the same reason: this tool can
    only prove a column transferred correctly when the source actually had it.
    """
    cursor = connection.execute(f'PRAGMA table_info("{table.name}")')
    present = {str(row[1]) for row in cursor.fetchall()}
    return [column for column in table.columns if column.name in present]


def read_rows(
    connection: sqlite3.Connection,
    table: Table,
) -> list[dict[str, object]]:
    """Read one source table, coerced to the types the Postgres columns declare."""
    columns = transferable_columns(connection, table)
    quoted = ", ".join(f'"{column.name}"' for column in columns)
    cursor = connection.execute(f'SELECT {quoted} FROM "{table.name}"')  # noqa: S608
    return [
        {column.name: coerce_value(row[column.name], column) for column in columns}
        for row in cursor.fetchall()
    ]


def coerce_value(value: object, column: Column[object]) -> object:
    """Convert one SQLite value to what the Postgres column expects."""
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, Boolean):
        return _as_bool(value)
    if _is_timestamptz(column):
        return _as_datetime(value)
    if isinstance(column_type, Integer):
        return int(cast("int", value))
    if isinstance(column_type, Float):
        return float(cast("float", value))
    return value


def checksum(rows: Sequence[dict[str, object]], column_names: Sequence[str]) -> str:
    """Hash a table's rows from a canonical, engine-independent representation.

    The rendered rows are sorted here rather than by either engine. Sorting in
    SQL would compare text under SQLite's BINARY collation on one side and the
    cluster's collation (en_US.utf8 in the shipped image) on the other, so any
    table with a text key would checksum differently after a correct transfer.
    A relational table has no inherent row order, so ordering is not a property
    worth proving — the multiset of rows is.

    ``column_names`` is explicit rather than read off ``rows``' own keys so both
    sides of a comparison hash the same columns even when a target row (read
    from Postgres, every column present) has more keys than a source row (read
    from SQLite, see :func:`transferable_columns`).
    """
    digest = hashlib.sha256()
    lines = sorted(
        FIELD_SEPARATOR.join(canonical(row.get(name)) for name in column_names) for row in rows
    )
    for line in lines:
        digest.update(line.encode())
        digest.update(ROW_SEPARATOR.encode())
    return digest.hexdigest()


def canonical(value: object) -> str:
    """Render a value the same way regardless of which engine produced it."""
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    return str(value)


async def transfer(
    connection: sqlite3.Connection,
    engine: AsyncEngine,
    *,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> TransferReport:
    """Copy every modelled table, then verify counts and checksums."""
    reports: list[TableReport] = []
    for table_name in source_tables(connection):
        table = metadata.tables[table_name]
        column_names = [column.name for column in transferable_columns(connection, table)]
        rows = read_rows(connection, table)
        source_checksum = checksum(rows, column_names)

        if not dry_run and rows:
            await _write_rows(engine, table, rows, batch_size)

        # A dry run writes nothing, so there is no target to compare against:
        # the target figures below echo the source and TableReport.ok is
        # vacuously true. Dry-run previews volume; only --mode verify proves
        # anything. _print_report says so in the operator's output.
        target_rows = [] if dry_run else await _read_target(engine, table)
        reports.append(
            TableReport(
                table=table_name,
                source_rows=len(rows),
                target_rows=len(rows) if dry_run else len(target_rows),
                source_checksum=source_checksum,
                target_checksum=(
                    source_checksum if dry_run else checksum(target_rows, column_names)
                ),
            )
        )
        log.info("table_transferred", table=table_name, rows=len(rows), dry_run=dry_run)

    if not dry_run:
        await align_sequences(engine)
    return TransferReport(tables=tuple(reports), dry_run=dry_run)


async def verify(connection: sqlite3.Connection, engine: AsyncEngine) -> TransferReport:
    """Compare an already-imported Postgres against the source, without writing."""
    reports: list[TableReport] = []
    for table_name in source_tables(connection):
        table = metadata.tables[table_name]
        column_names = [column.name for column in transferable_columns(connection, table)]
        rows = read_rows(connection, table)
        target_rows = await _read_target(engine, table)
        reports.append(
            TableReport(
                table=table_name,
                source_rows=len(rows),
                target_rows=len(target_rows),
                source_checksum=checksum(rows, column_names),
                target_checksum=checksum(target_rows, column_names),
            )
        )
    return TransferReport(tables=tuple(reports), dry_run=False)


async def align_sequences(engine: AsyncEngine) -> dict[str, int]:
    """Advance each identity sequence past the highest imported id.

    Without this the first insert after a migration collides with a row that was
    copied in, because the sequence still sits at 1.
    """
    aligned: dict[str, int] = {}
    async with engine.begin() as connection:
        for table in metadata.sorted_tables:
            column = _sequence_column(table)
            if column is None:
                continue
            result = await connection.execute(
                text(
                    "SELECT setval("
                    "  pg_get_serial_sequence(:table_name, :column_name),"
                    f'  COALESCE((SELECT MAX("{column.name}") FROM "{table.name}"), 0) + 1,'  # noqa: S608
                    "  false)"
                ).bindparams(table_name=table.name, column_name=column.name),
            )
            value = result.scalar_one_or_none()
            if value is not None:
                aligned[table.name] = int(value)
    return aligned


async def _write_rows(
    engine: AsyncEngine,
    table: Table,
    rows: Sequence[dict[str, object]],
    batch_size: int,
) -> None:
    async with engine.begin() as connection:
        for batch in _batched(rows, batch_size):
            await connection.execute(insert(table), list(batch))


async def _read_target(engine: AsyncEngine, table: Table) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        result = await connection.execute(select(table))
        return [dict(row) for row in result.mappings()]


def _sequence_column(table: Table) -> Column[object] | None:
    for column in table.primary_key.columns:
        if isinstance(column.type, Integer) and column.autoincrement is not False:
            return column
    return None


def _is_timestamptz(column: Column[object]) -> bool:
    return getattr(column.type, "timezone", False) is True


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes"}
    return bool(value)


def _as_datetime(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else _parse_timestamp(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_timestamp(raw: str) -> datetime:
    candidate = raw.strip().replace(" ", "T", 1)
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        msg = f"cannot parse timestamp {raw!r}"
        raise ValueError(msg) from exc


def _batched(
    rows: Sequence[dict[str, object]],
    size: int,
) -> Iterator[Sequence[dict[str, object]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
