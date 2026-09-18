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

It reads `~/.config/sophia/env` itself (`SOPHIA_ENV_FILE` overrides) rather than
relying on a sourced shell profile, because `/ship` runs SESSION_CMD in an
environment that has never sourced anything. That also keeps
SOPHIA_KEYRING_PASSWORD out of every other process's environment. Anything
already set in the environment wins.

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
import stat
import sys
from pathlib import Path
from typing import cast

import redis.asyncio as redis_asyncio
from platformdirs import user_config_dir
from redis.exceptions import ConnectionError as RedisConnectionError

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


def _load_env_file() -> Path | None:
    """Read the operator's env file, so only this script ever holds its secrets.

    `/ship` runs SESSION_CMD in whatever environment the harness has, which has
    never sourced this file. Reading it here rather than from a shell profile
    keeps SOPHIA_KEYRING_PASSWORD out of the environment of every other process.

    Anything already set wins, so gates.sh and an explicit override still do.
    """
    override = os.environ.get("SOPHIA_ENV_FILE")
    config_dir = os.environ.get("SOPHIA_CONFIG_DIR") or user_config_dir("sophia")
    path = Path(override) if override else Path(config_dir) / "env"
    if not path.is_file():
        return None

    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(
            f"warning: {path} is readable beyond its owner — chmod 600 it",
            file=sys.stderr,
        )

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.removeprefix("export ").strip().partition("=")
        if not sep:
            continue
        value = value.strip()
        # Quotes are stripped here because this is not a shell: an unquoted
        # password containing & would have been mangled by one, which is the
        # whole reason this file is read rather than sourced.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)
    return path


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


def _warn_if_study_unreachable(tenant: SessionTenant) -> None:
    """Say at mint time when this session cannot reach the study surface.

    `frontend/src/routes/study/+page.server.ts:13` coerces learning_path_id with
    `Number()` and bails unless the result is a positive integer, so the
    non-numeric `default-learning-path` sentinel every real login gets makes
    /app/study unreachable. That is #106, and it is reproduced here rather than
    papered over — see the module docstring. Printing it is what keeps it from
    being discovered halfway through a walk.
    """
    raw = tenant.learning_path_id
    if raw.isdigit() and int(raw) > 0:
        return
    print(
        f"warning: learning_path_id is {raw!r}, not a positive integer, so "
        "/app/study is unreachable for this session — that is #106, not a "
        "fault in the walk. Settings, auth and language flows are unaffected. "
        "--learning-path-id gets past it; name that in proof.md if you use it.",
        file=sys.stderr,
    )


async def _mint(learning_path_id: str | None) -> str:
    # Before Settings(), which reads SOPHIA_* out of the environment.
    _load_env_file()
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
    _warn_if_study_unreachable(tenant)
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
    except RedisConnectionError as exc:
        # Run by hand this is almost always "the stack is not up", and a
        # connection traceback buries that under forty lines.
        msg = (
            f"cannot reach Redis at {settings.redis_url}: {exc}\n"
            "Start the stack first (scripts/run_stack.sh), and set "
            "SOPHIA_REDIS_URL to the same Redis it uses — .claude/gates.sh "
            "exports both so /ship keeps them in step."
        )
        raise SystemExit(msg) from None
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
