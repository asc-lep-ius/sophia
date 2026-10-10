"""Topics, ratings and reviews keyed by the course that owns a module, not the module.

The pipeline and the CLI filed a course's topics under an Opencast module id,
while the browser reads everything under the TUWEL course id, the learning
path, so nothing processed ever reached a course in the browser (#127). This
moves every row of ``topic_mappings``, ``topic_lecture_links``,
``topic_reconciliations``, ``confidence_ratings`` and ``review_schedule`` that
is keyed by a module id to the course discovery recorded as the module's
owner in ``lecture_modules``.

A row counts as keyed by a module id when its ``course_id`` is the id of a
module the database knows of, through discovery, a download or a transcript.
Two kinds of such row are left where they are, and logged by table, module and
count rather than dropped:

* its module has no recorded owner. Run discovery, then downgrade and upgrade
  again to move them;
* moving it would collide with a row its course already holds under the same
  key, the same topic from two modules for instance. The one from the lowest
  module id moves; merging the others would lose a row.

``module_course_rekeys`` records where every moved row came from, so the
downgrade puts each one back under its own module rather than leaving the rows
of two modules of one course merged under the course. A row written under the
course after the upgrade has no record, and stays where it is.

Revision ID: 0005_topics_keyed_by_course
Revises: 0004_transcription_source
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, NamedTuple

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection, RowMapping

revision: str = "0005_topics_keyed_by_course"
down_revision: str | None = "0004_transcription_source"
branch_labels: str | None = None
depends_on: str | None = None

log = logging.getLogger("alembic.runtime.migration")

_REKEYS = "module_course_rekeys"

# The provenance column each identity column is recorded in.
_RECORDED_AS = {"id": "row_id", "topic": "topic", "chunk_id": "chunk_id"}


# A NamedTuple, not a dataclass: Alembic loads this file outside sys.modules,
# and a dataclass looks its own module up there.
class _KeyedTable(NamedTuple):
    name: str
    # The columns that find one row again, course_id aside.
    identity: tuple[str, ...]
    # The columns that, with course_id, may hold a value only once.
    unique: tuple[str, ...]

    @property
    def columns(self) -> list[str]:
        return list(dict.fromkeys((*self.identity, *self.unique)))


_TABLES = (
    _KeyedTable("topic_mappings", ("id",), ("topic", "source")),
    _KeyedTable("topic_reconciliations", ("id",), ("manual_topic",)),
    _KeyedTable("topic_lecture_links", ("topic", "chunk_id"), ("topic", "chunk_id")),
    _KeyedTable("review_schedule", ("topic",), ("topic",)),
    _KeyedTable("confidence_ratings", ("id",), ()),
)


def upgrade() -> None:
    op.create_table(
        _REKEYS,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("row_id", sa.Integer(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("chunk_id", sa.Text(), nullable=True),
        sa.Column("module_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Text(), server_default="default", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_course_rekeys")),
    )

    connection = op.get_bind()
    owners = _module_owners(connection)
    modules = _known_modules(connection)
    for table in _TABLES:
        _rekey(connection, table, owners, modules)


def downgrade() -> None:
    connection = op.get_bind()
    for table in _TABLES:
        match = " AND ".join(f"t.{column} = r.{_RECORDED_AS[column]}" for column in table.identity)
        connection.execute(
            sa.text(
                f"UPDATE {table.name} AS t SET course_id = r.module_id "
                f"FROM {_REKEYS} AS r "
                f"WHERE r.table_name = :table AND t.course_id = r.course_id AND {match}"
            ),
            {"table": table.name},
        )
    op.drop_table(_REKEYS)


def _module_owners(connection: Connection) -> dict[int, int]:
    rows = connection.execute(
        sa.text("SELECT module_id, course_id FROM lecture_modules WHERE course_id ~ '^[0-9]+$'")
    )
    return {row.module_id: int(row.course_id) for row in rows}


def _known_modules(connection: Connection) -> list[int]:
    rows = connection.execute(
        sa.text(
            "SELECT module_id FROM lecture_modules "
            "UNION SELECT module_id FROM lecture_downloads "
            "UNION SELECT module_id FROM transcriptions"
        )
    )
    return sorted(row.module_id for row in rows)


def _rekey(
    connection: Connection,
    table: _KeyedTable,
    owners: dict[int, int],
    modules: list[int],
) -> None:
    rows = _select_in(connection, table, "course_id", modules)
    courses = sorted({owners[row["course_id"]] for row in rows if row["course_id"] in owners})
    taken = _taken_keys(connection, table, courses)
    moved: Counter[tuple[int, int]] = Counter()
    left: defaultdict[tuple[int, str], list[str]] = defaultdict(list)

    for row in rows:
        module_id = row["course_id"]
        course_id = owners.get(module_id)
        key = (course_id, *(row[column] for column in table.unique))
        if course_id is None:
            left[module_id, "it has no recorded owner"].append(_name(table, row))
        elif table.unique and key in taken:
            left[module_id, f"course {course_id} already holds its key"].append(_name(table, row))
        else:
            taken.add(key)
            _move(connection, table, row, course_id)
            moved[module_id, course_id] += 1

    for (module_id, course_id), count in sorted(moved.items()):
        log.info(
            "%s: %d row(s) moved from module %d to course %d",
            table.name,
            count,
            module_id,
            course_id,
        )
    for (module_id, reason), names in sorted(left.items()):
        log.warning(
            "%s: %d row(s) left under module %d, because %s: %s",
            table.name,
            len(names),
            module_id,
            reason,
            ", ".join(names),
        )


def _name(table: _KeyedTable, row: RowMapping) -> str:
    return "/".join(str(row[column]) for column in table.columns)


def _select_in(
    connection: Connection,
    table: _KeyedTable,
    column: str,
    values: Sequence[int],
) -> Sequence[RowMapping]:
    """Rows whose ``column`` is one of ``values``, oldest module and row first."""
    selected = ", ".join(table.columns)
    order = ", ".join(table.identity)
    statement = sa.text(
        f"SELECT course_id, {selected} FROM {table.name} "
        f"WHERE {column} IN :values ORDER BY course_id, {order}"
    ).bindparams(sa.bindparam("values", expanding=True))
    return connection.execute(statement, {"values": list(values)}).mappings().all()


def _taken_keys(
    connection: Connection,
    table: _KeyedTable,
    courses: list[int],
) -> set[tuple[object, ...]]:
    if not table.unique:
        return set()
    rows = _select_in(connection, table, "course_id", courses)
    return {(row["course_id"], *(row[column] for column in table.unique)) for row in rows}


def _move(connection: Connection, table: _KeyedTable, row: RowMapping, course_id: int) -> None:
    identity = {column: row[column] for column in table.identity}
    match = " AND ".join(f"{column} = :{column}" for column in table.identity)
    connection.execute(
        sa.text(
            f"UPDATE {table.name} SET course_id = :course_id "
            f"WHERE course_id = :module_id AND {match}"
        ),
        {"course_id": course_id, "module_id": row["course_id"], **identity},
    )
    recorded = {_RECORDED_AS[column]: value for column, value in identity.items()}
    connection.execute(
        sa.text(
            f"INSERT INTO {_REKEYS} "
            "(table_name, row_id, topic, chunk_id, module_id, course_id) "
            "VALUES (:table_name, :row_id, :topic, :chunk_id, :module_id, :course_id)"
        ),
        {
            "table_name": table.name,
            "row_id": recorded.get("row_id"),
            "topic": recorded.get("topic"),
            "chunk_id": recorded.get("chunk_id"),
            "module_id": row["course_id"],
            "course_id": course_id,
        },
    )
