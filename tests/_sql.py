"""Literal-SQL helper for database tests.

Test fixtures state their rows as SQL because that is the clearest way to show
what a scenario starts from. Production code uses Core expressions; here the
literal form earns its place, so this helper carries it across the two
differences that would otherwise force every fixture to be rewritten:

* positional ``?`` placeholders become named binds, which is what SQLAlchemy
  accepts;
* SQLite's ``INSERT OR REPLACE`` / ``INSERT OR IGNORE`` become the ``ON
  CONFLICT`` forms Postgres spells them with.

Anything past that is a real dialect difference and belongs written out in the
test rather than papered over here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import String, Text, text

from sophia.infra.schema import metadata
from sophia.infra.sqlite_import import coerce_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Column
    from sqlalchemy.engine import Result
    from sqlalchemy.ext.asyncio import AsyncSession

_INSERT_TARGET = re.compile(
    r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)
_SQLITE_NOW = re.compile(r"datetime\(\s*'now'\s*\)", re.IGNORECASE)
_OR_REPLACE = re.compile(r"INSERT\s+OR\s+REPLACE\s+INTO", re.IGNORECASE)
_OR_IGNORE = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)
_INSERT_COLUMNS = re.compile(r"\(([^)]*)\)\s*VALUES", re.IGNORECASE | re.DOTALL)


def coerce_insert_params(sql: str, params: Sequence[object]) -> list[object]:
    """Coerce fixture values to the types the target columns declare.

    Tests write timestamps as ISO strings because that is readable; asyncpg
    wants real datetimes for ``TIMESTAMPTZ`` and real strings for the columns
    Chronos deliberately keeps as text. The schema knows which is which, so
    this asks it rather than guessing from the value.
    """
    target = _INSERT_TARGET.search(sql)
    if target is None:
        return list(params)
    table = metadata.tables.get(target.group(1))
    if table is None:
        return list(params)

    names = [name.strip() for name in target.group(2).split(",") if name.strip()]
    values = [value.strip() for value in target.group(3).split(",")]
    if len(names) != len(values):
        return list(params)

    # Only the "?" slots consume parameters; the rest are SQL literals.
    placeholder_columns = [name for name, value in zip(names, values, strict=True) if value == "?"]
    if len(placeholder_columns) != len(params):
        return list(params)
    return [
        _for_column(value, table.columns[name]) if name in table.columns else value
        for name, value in zip(placeholder_columns, params, strict=True)
    ]


def _for_column(value: object, column: Column[Any]) -> object:
    """Coerce one fixture value to the column's declared type.

    Beyond the SQLite-to-Postgres conversions the migration script does, tests
    also pass integers for the text ``course_id``/``org_id`` columns migration
    022 introduced, which SQLite accepted and Postgres will not.
    """
    if isinstance(column.type, Text | String) and value is not None and not isinstance(value, str):
        return str(value)
    return coerce_value(value, column)


def to_named_binds(sql: str, params: Sequence[object]) -> tuple[str, dict[str, object]]:
    """Rewrite ``?`` placeholders as ``:p0``-style binds.

    A ``?`` inside a quoted literal is data, not a placeholder — fixtures do
    write flashcard fronts like ``'Q?'`` — so the scan tracks string state.
    """
    bound: dict[str, object] = {}
    rendered: list[str] = []
    index = 0
    in_literal = False
    for char in sql:
        if char == "'":
            in_literal = not in_literal
        if char == "?" and not in_literal:
            name = f"p{index}"
            bound[name] = params[index]
            rendered.append(f":{name}")
            index += 1
        else:
            rendered.append(char)
    if index != len(params):
        msg = f"statement has {index} placeholders but {len(params)} parameters"
        raise ValueError(msg)
    return "".join(rendered), bound


async def exec_sql(
    db: AsyncSession,
    sql: str,
    params: Sequence[object] = (),
    *,
    conflict: str = "",
) -> Result[Any]:
    """Execute literal SQL written in the SQLite dialect these tests were built in.

    ``conflict`` names the columns an upsert keys on; Postgres requires them to
    be explicit where SQLite inferred them.
    """
    statement, bound = to_named_binds(_translate(sql), coerce_insert_params(sql, params))
    is_ignore = bool(_OR_IGNORE.search(statement))
    if is_ignore or _OR_REPLACE.search(statement):
        if not conflict:
            msg = "upserts need conflict= naming the conflicting columns"
            raise ValueError(msg)
        action = "NOTHING" if is_ignore else _do_update(statement, conflict)
        statement = _OR_IGNORE.sub("INSERT INTO", _OR_REPLACE.sub("INSERT INTO", statement))
        statement = f"{statement} ON CONFLICT ({conflict}) DO {action}"
    return await db.execute(text(statement), bound)


def _translate(sql: str) -> str:
    """Swap the SQLite spellings Postgres does not share."""
    return _SQLITE_NOW.sub("now()", sql)


def _do_update(statement: str, conflict: str) -> str:
    """Build the SET clause an OR REPLACE implies, minus the conflict columns."""
    columns = _INSERT_COLUMNS.search(statement)
    if columns is None:
        msg = "cannot infer the inserted columns from the statement"
        raise ValueError(msg)
    keys = {name.strip() for name in conflict.split(",")}
    names = [
        name.strip()
        for name in columns.group(1).split(",")
        if name.strip() and name.strip() not in keys
    ]
    if not names:
        return "NOTHING"
    return "UPDATE SET " + ", ".join(f"{name} = EXCLUDED.{name}" for name in names)
