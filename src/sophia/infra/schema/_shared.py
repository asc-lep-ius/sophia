"""Shared metadata and column conventions for the Postgres schema.

The schema is a faithful port of the SQLite tables migration 001-024 built up,
not a redesign — issue #96 puts schema changes out of scope. Two things could
not be carried across verbatim, because SQLite's dynamic typing let them stay
ambiguous and Postgres will not:

* ``BOOLEAN`` columns held 0/1 integers in SQLite and become real booleans here.
* Columns declared ``TIMESTAMP`` become ``TIMESTAMP WITH TIME ZONE``; columns
  declared ``TEXT`` that happen to hold ISO-8601 stay text, so their existing
  lexicographic ordering keeps working.

The ``org_id``/``course_id`` type split inherited from migration 022 (text on
some tables, integer on others) is preserved deliberately. Unifying it is a
schema change, and doing it silently inside a database migration is how row
counts stay green while meaning drifts.
"""

from __future__ import annotations

from sqlalchemy import Column, MetaData, Text

# Explicit naming convention so Alembic autogenerate emits stable, reviewable
# constraint names instead of database-assigned ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

DEFAULT_SCOPE = "default"


def org_id_column() -> Column[str]:
    """Tenancy scope every persisted table carries, read by ``SET LOCAL app.org_id``."""
    return Column("org_id", Text, nullable=False, server_default=DEFAULT_SCOPE)


def text_course_id_column() -> Column[str]:
    """Course scope on tables that gained it as text in migration 022."""
    return Column("course_id", Text, nullable=False, server_default=DEFAULT_SCOPE)
