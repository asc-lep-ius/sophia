"""One transaction per request, closed inside the exception-handled region."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from fastapi import APIRouter, Request
from sqlalchemy import text

from sophia.api.deps import request_session
from sophia.api.transactions import TransactionalRoute
from sophia.infra.engine import create_session_factory, current_org_setting

from ._helpers import db_client

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres


@dataclass(frozen=True)
class DbAppContainer:
    """Minimal container exposing only what the session dependency needs."""

    session_factory: async_sessionmaker[AsyncSession]

    def session(self, *, org_id: str | None = None):
        from sophia.infra.engine import session_scope

        return session_scope(self.session_factory, org_id=org_id)


def container_for(engine: AsyncEngine) -> DbAppContainer:
    return DbAppContainer(session_factory=create_session_factory(engine))


def build_router() -> APIRouter:
    router = APIRouter(route_class=TransactionalRoute)

    @router.post("/probe/write")
    async def write(request: Request) -> dict[str, int]:
        session = await request_session(request)
        await session.execute(
            text(
                "INSERT INTO student_flashcards (course_id, topic, front, back) "
                "VALUES (12, 'Graphs', 'Q', 'A')"
            )
        )
        return {"written": 1}

    @router.post("/probe/write-then-fail")
    async def write_then_fail(request: Request) -> dict[str, int]:
        session = await request_session(request)
        await session.execute(
            text(
                "INSERT INTO student_flashcards (course_id, topic, front, back) "
                "VALUES (12, 'Graphs', 'Q', 'A')"
            )
        )
        msg = "handler failed after writing"
        raise RuntimeError(msg)

    @router.post("/probe/two-writes-second-invalid")
    async def two_writes(request: Request) -> dict[str, int]:
        session = await request_session(request)
        await session.execute(
            text(
                "INSERT INTO student_flashcards (course_id, topic, front, back) "
                "VALUES (12, 'Graphs', 'first', 'A')"
            )
        )
        # Violates the predicted-ratio check constraint, so the commit fails.
        await session.execute(
            text(
                "INSERT INTO confidence_ratings (topic, course_id, predicted) "
                "VALUES ('Graphs', 12, 4.2)"
            )
        )
        return {"written": 2}

    @router.get("/probe/org")
    async def org(request: Request) -> dict[str, str]:
        session = await request_session(request)
        return {"org_id": await current_org_setting(session)}

    @router.get("/probe/same-session")
    async def same_session(request: Request) -> dict[str, bool]:
        first = await request_session(request)
        second = await request_session(request)
        return {"same": first is second}

    return router


async def count_flashcards(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return cast("int", await connection.scalar(text("SELECT count(*) FROM student_flashcards")))


async def test_a_successful_request_commits(clean_engine: AsyncEngine) -> None:
    async with db_client(container_for(clean_engine), build_router()) as client:
        response = await client.post("/api/probe/write")

    assert response.status_code == 200
    assert await count_flashcards(clean_engine) == 1


async def test_a_failing_handler_rolls_the_whole_request_back(
    clean_engine: AsyncEngine,
) -> None:
    async with db_client(container_for(clean_engine), build_router()) as client:
        response = await client.post("/api/probe/write-then-fail")

    assert response.status_code == 500
    assert await count_flashcards(clean_engine) == 0


async def test_a_failing_commit_reaches_the_client_as_an_error(
    clean_engine: AsyncEngine,
) -> None:
    """The reason the commit is not left to dependency teardown.

    FastAPI runs teardown after the response is produced, so a commit that fails
    there would return 200 while writing nothing.
    """
    async with db_client(container_for(clean_engine), build_router()) as client:
        response = await client.post("/api/probe/two-writes-second-invalid")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "sophia.failed"
    assert await count_flashcards(clean_engine) == 0


async def test_the_request_org_scope_reaches_the_transaction(
    clean_engine: AsyncEngine,
) -> None:
    async with db_client(container_for(clean_engine), build_router()) as client:
        response = await client.get("/api/probe/org")

    assert response.json()["org_id"] == "local"


async def test_two_dependencies_share_one_session(clean_engine: AsyncEngine) -> None:
    """Two services in one handler must land in the same transaction."""
    async with db_client(container_for(clean_engine), build_router()) as client:
        response = await client.get("/api/probe/same-session")

    assert response.json()["same"] is True


async def test_a_router_without_the_route_class_fails_loudly() -> None:
    """A new router that forgets TransactionalRoute must not silently autocommit."""
    from fastapi import FastAPI

    from sophia.api.transactions import get_transaction_stack

    app = FastAPI()
    plain = APIRouter()

    @plain.get("/no-stack")
    async def no_stack(request: Request) -> dict[str, str]:
        get_transaction_stack(request)
        return {}

    app.include_router(plain)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/no-stack")

    assert response.status_code == 500
