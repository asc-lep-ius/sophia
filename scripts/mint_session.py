"""Mint a browser session against the real stack, for /ship step 2c.

Prints one line a browser can carry — `<cookie-name>=<value>` — as its last
line of stdout. `.claude/gates.sh` records it as SESSION_CMD.

This exists because the proof walk has to sign in the way a person does. It
carries the operator's real TUWEL and TISS session rather than a faked identity,
which is deliberate: a fake session lands in an empty workspace, because
`course_materials`, `lecture_modules` and `topic_mappings` stay empty until a
TUWEL sync has run. A walk through that proves nothing about the study surface.
The cost is that this is box-bound — see docs/run-contract-setup.md.

It does not re-run the interactive login. `ensure_valid_session` checks the
stored session and, when it has expired, re-authenticates from the keyring with
no MFA code, exactly as the scheduled job runner does.

The tenant is left at its real default on purpose. `SessionTenant()` gives
`learning_path_id="default-learning-path"`, the non-numeric sentinel every real
login gets and every consumer coerces with `Number()` — the #106 bug. Seeding a
numeric id here would hide it again, which is what `tests/e2e/shell-auth.ts`
does. Pass --learning-path-id only when a walk genuinely needs to get past it,
and say so in proof.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import cast

import redis.asyncio as redis_asyncio

from sophia.adapters.auth import (
    load_credentials_from_keyring,
    load_session,
    load_tiss_session,
    session_path,
    tiss_session_path,
)
from sophia.api.sessions import (
    RedisSessionBackend,
    SessionCredential,
    SessionTenant,
    SessionUser,
    create_session_core,
    create_session_record,
)
from sophia.config import Settings
from sophia.services.job_runner import ensure_valid_session


def _resolve_username() -> str:
    """The learner id the session is minted for, never their password."""
    from_env = os.environ.get("SOPHIA_TUWEL_USERNAME")
    if from_env:
        return from_env
    stored = load_credentials_from_keyring()
    if stored is not None:
        return stored[0]
    msg = (
        "no username available — set SOPHIA_TUWEL_USERNAME, or run "
        "`sophia auth login --save-credentials` so it can be read back"
    )
    raise SystemExit(msg)


async def _mint(learning_path_id: str | None) -> str:
    settings = Settings()

    if not await ensure_valid_session(settings.config_dir, settings.tuwel_host, settings.tiss_host):
        msg = "no valid TUWEL session and none could be refreshed — see docs/run-contract-setup.md"
        raise SystemExit(msg)

    tuwel = load_session(session_path(settings.config_dir))
    if tuwel is None:
        msg = "ensure_valid_session reported success but no session was saved"
        raise SystemExit(msg)
    tiss = load_tiss_session(tiss_session_path(settings.config_dir))

    tenant = (
        SessionTenant(learning_path_id=learning_path_id) if learning_path_id else SessionTenant()
    )
    record = create_session_record(
        user=SessionUser(id=_resolve_username()),
        tenant=tenant,
        tuwel_credentials=SessionCredential(
            payload={
                "moodle_session": tuwel.moodle_session,
                "sesskey": tuwel.sesskey,
                "host": tuwel.host,
                "created_at": tuwel.created_at,
                "cookie_name": tuwel.cookie_name,
            }
        ),
        tiss_credentials=(
            SessionCredential(
                payload={
                    "jsessionid": tiss.jsessionid,
                    "tiss_session": tiss.tiss_session,
                    "host": tiss.host,
                    "created_at": tiss.created_at,
                    "cookies": tiss.cookies,
                }
            )
            if tiss is not None
            else None
        ),
    )

    # The same Redis and the same signing key the running API uses, or the
    # cookie it returns verifies against nothing.
    client = redis_asyncio.Redis.from_url(settings.redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        core = create_session_core(settings, cast("RedisSessionBackend", client))
        cookie = await core.create(record)
    finally:
        await client.aclose()

    print(f"minted for {record.user.id}, tenant {record.tenant.learning_path_id}", file=sys.stderr)
    return f"{settings.session_cookie_name}={cookie}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--learning-path-id",
        help="override the real default; hides #106, so name it in proof.md",
    )
    args = parser.parse_args()
    print(asyncio.run(_mint(args.learning_path_id)))


if __name__ == "__main__":
    main()
