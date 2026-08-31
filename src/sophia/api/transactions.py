"""Request-scoped database transactions.

One transaction per request, so a handler that calls two services either records
both effects or neither, and so the org scope bound at ``BEGIN`` covers every
statement the request makes.

The transaction is committed by a custom route class rather than by a ``yield``
dependency. FastAPI runs dependency teardown *after* the response is produced,
so a commit that fails there cannot change the status code — the client is told
200 while nothing was written. Committing inside the route handler keeps the
failure inside the region FastAPI's exception handlers cover, so a failed commit
becomes a 500 with the normal error envelope.

The stack is entered on every request but only opens a session if a handler
actually asks for one, so routes that touch no data pay nothing.

A streaming route must not take ``request_session``. The exit stack closes when
the handler returns, which for a ``StreamingResponse`` is before the body
generator runs, so the session would already be closed by the time the generator
touched it. Read what the stream needs before returning the response.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, cast

from fastapi.routing import APIRoute

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from fastapi import Request
    from starlette.responses import Response

_STACK_STATE_ATTR = "sophia_db_stack"


class TransactionalRoute(APIRoute):
    """Route class that closes the request's database transaction in-band."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def transactional_handler(request: Request) -> Response:
            stack: AsyncExitStack[bool | None]
            async with AsyncExitStack() as stack:
                setattr(request.state, _STACK_STATE_ATTR, stack)
                return await original_handler(request)

        return transactional_handler


def get_transaction_stack(request: Request) -> AsyncExitStack[bool | None]:
    """Return the stack the request's session should be entered into."""
    stack = cast("object", getattr(request.state, _STACK_STATE_ATTR, None))
    if not isinstance(stack, AsyncExitStack):
        msg = "no request transaction stack — the router must use TransactionalRoute"
        raise RuntimeError(msg)
    return cast("AsyncExitStack[bool | None]", stack)
