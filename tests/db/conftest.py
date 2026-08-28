"""Postgres-backed test fixtures.

The database is real rather than faked: the whole point of issue #96 is
behaviour SQLite cannot express — transaction-scoped settings, real booleans,
timezone-aware timestamps — so a fake would test the wrong thing.

Availability is a hard failure, not a skip. A suite that quietly skips its
database tests when the database is missing reports green while proving
nothing, which is precisely the outcome the org-context hook cannot afford.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from sophia.infra.alembic_runner import upgrade
from sophia.infra.engine import create_engine, create_session_factory
from sophia.infra.schema import metadata

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://sophia:sophia@localhost:5432/sophia_test"
TEST_DATABASE_URL_ENV = "SOPHIA_TEST_DATABASE_URL"


def test_database_url() -> str:
    """Resolve the test database, honouring the CI service's URL."""
    return os.environ.get(TEST_DATABASE_URL_ENV, DEFAULT_TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    return test_database_url()


@pytest.fixture(scope="session")
def migrated_database(postgres_url: str) -> str:
    """Bring the test database to head once for the whole session."""
    upgrade(postgres_url)
    return postgres_url


@pytest.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """A fresh engine per test, so pool behaviour in one test cannot affect another."""
    async_engine = create_engine(migrated_database, pool_size=2, max_overflow=0)
    try:
        yield async_engine
    finally:
        await async_engine.dispose()


@pytest.fixture
async def clean_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """An engine whose tables are emptied afterwards.

    Used by tests that must genuinely commit — a migration import, or a check
    that a setting did *not* survive a commit — where wrapping the test in a
    rolled-back outer transaction would hide the thing under test.
    """
    try:
        yield engine
    finally:
        await truncate_all(engine)


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def truncate_all(engine: AsyncEngine) -> None:
    """Empty every modelled table and restart its identity sequence."""
    table_list = ", ".join(f'"{table.name}"' for table in metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
