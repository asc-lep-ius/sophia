"""The org-context hook: set inside the transaction, gone after it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from sophia.infra.engine import (
    ORG_SETTING,
    apply_org_context,
    check_connection,
    commit_unit,
    create_session_factory,
    current_org_setting,
    session_scope,
)
from sophia.infra.org_context import DEFAULT_ORG_ID, get_org_id, org_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres

_INSERT_FLASHCARD = text(
    "INSERT INTO student_flashcards (course_id, topic, front, back) VALUES (12, :topic, 'Q', 'A')"
)


async def test_org_context_is_visible_inside_the_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory, org_id="tu-wien") as session:
        assert await current_org_setting(session) == "tu-wien"


async def test_org_context_is_cleared_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SET LOCAL is transaction-scoped: the next transaction must not inherit it."""
    async with session_scope(session_factory, org_id="tu-wien"):
        pass

    async with session_factory() as session, session.begin():
        assert await current_org_setting(session) == ""


async def test_org_context_is_cleared_after_rollback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="deliberate"):
        async with session_scope(session_factory, org_id="tu-wien"):
            msg = "deliberate failure inside the transaction"
            raise RuntimeError(msg)

    async with session_factory() as session, session.begin():
        assert await current_org_setting(session) == ""


async def test_org_context_does_not_leak_between_tenants_on_a_pooled_connection(
    engine: AsyncEngine,
) -> None:
    """The pool hands the same physical connection to the next tenant."""
    from sophia.infra.engine import create_session_factory

    factory = create_session_factory(engine)
    seen: list[str] = []

    for org_id in ("org-a", "org-b", "org-c"):
        async with session_scope(factory, org_id=org_id) as session:
            seen.append(await current_org_setting(session))
        async with factory() as session, session.begin():
            seen.append(await current_org_setting(session))

    assert seen == ["org-a", "", "org-b", "", "org-c", ""]


async def test_a_write_after_a_unit_commit_still_carries_the_org(
    clean_engine: AsyncEngine,
) -> None:
    """The commit ends the transaction SET LOCAL was bound to; the next one is bound again."""
    async with session_scope(create_session_factory(clean_engine), org_id="tu-wien") as session:
        await commit_unit(session)
        await session.execute(_INSERT_FLASHCARD, {"topic": "after"})
        assert await current_org_setting(session) == "tu-wien"


async def test_a_failure_after_a_unit_commit_keeps_what_was_committed(
    clean_engine: AsyncEngine,
) -> None:
    factory = create_session_factory(clean_engine)

    with pytest.raises(RuntimeError, match="deliberate"):
        async with session_scope(factory, org_id="tu-wien") as session:
            await session.execute(_INSERT_FLASHCARD, {"topic": "finished"})
            await commit_unit(session)
            await session.execute(_INSERT_FLASHCARD, {"topic": "in flight"})
            msg = "deliberate failure after the commit"
            raise RuntimeError(msg)

    async with session_scope(factory, org_id="tu-wien") as reader:
        topics = (await reader.scalars(text("SELECT topic FROM student_flashcards"))).all()
    assert topics == ["finished"]


async def test_commit_unit_refuses_a_session_with_no_recorded_org(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Rebinding to the ambient scope could bind another tenant than the one begun with."""
    async with session_factory() as session, session.begin():
        with pytest.raises(RuntimeError, match="session_scope"):
            await commit_unit(session)


async def test_org_context_defaults_to_the_ambient_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with org_scope("ambient-org"):
        async with session_scope(session_factory) as session:
            assert await current_org_setting(session) == "ambient-org"


async def test_ambient_scope_is_restored_after_the_block() -> None:
    with org_scope("ambient-org"):
        assert get_org_id() == "ambient-org"
    assert get_org_id() == DEFAULT_ORG_ID


async def test_applying_org_context_outside_a_transaction_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A session-level SET would outlive the request on a pooled connection."""
    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="transaction-scoped"):
            await apply_org_context(session, "tu-wien")


async def test_org_setting_name_is_readable_by_a_future_rls_policy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """RLS policies will read current_setting('app.org_id'); prove the name matches."""
    async with session_scope(session_factory, org_id="tu-wien") as session:
        result = await session.execute(
            text("SELECT current_setting(:name, true)"),
            {"name": ORG_SETTING},
        )
        assert result.scalar_one() == "tu-wien"


async def test_check_connection_reports_a_reachable_database(engine: AsyncEngine) -> None:
    assert await check_connection(engine) is True


async def test_check_connection_reports_an_unreachable_database() -> None:
    from sophia.infra.engine import create_engine

    unreachable = create_engine("postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        assert await check_connection(unreachable) is False
    finally:
        await unreachable.dispose()
