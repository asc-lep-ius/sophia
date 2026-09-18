#!/usr/bin/env bash
# Start the stack /ship step 2c walks, on loopback high ports.
#
# Runs in the foreground; the harness backgrounds it into its own process group
# and kills that group to stop it. Redis is the one piece that outlives the
# group, because it is a container — STOP_CMD in .claude/gates.sh stops it.
#
# Not `docker compose up`: on hephaestus ports 80 and 443 belong to the homelab
# Caddy that fronts gitlab.hephaestus, and 5432 to the long-running dev Postgres
# that `docker compose down` here would stop. See docs/run-contract-setup.md.
#
# The browser talks to one origin. Vite proxies /api to the API, so the
# __Host- session cookie — which requires Secure and Path=/ on a single origin —
# is carried on the study calls and the SSE stream the same way Caddy carries it
# in production.
set -uo pipefail

API_PORT="${SOPHIA_STACK_API_PORT:-8001}"
WEB_PORT="${SOPHIA_STACK_WEB_PORT:-5173}"
REDIS_PORT="${SOPHIA_STACK_REDIS_PORT:-16379}"
REDIS_NAME="${SOPHIA_STACK_REDIS_NAME:-sophia-proof-redis}"
PG_URL="${SOPHIA_DATABASE_URL:-postgresql+asyncpg://sophia:sophia@127.0.0.1:5432/sophia}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
export PATH="$HOME/.local/bin:$PATH"

# Postgres is not started here. It is long-running and shared, and starting it
# would mean touching the compose project whose `down` stops it.
if ! (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null; then
    echo "postgres is not answering on 127.0.0.1:5432 — run \`make db.up\`" >&2
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$REDIS_NAME"; then
    docker run -d --rm --name "$REDIS_NAME" \
        -p "127.0.0.1:${REDIS_PORT}:6379" redis:8.6.3-alpine \
        redis-server --save '' --appendonly no >/dev/null || exit 1
fi

# Honoured rather than overwritten: .claude/gates.sh exports the same value so
# SESSION_CMD mints into the Redis this stack actually reads.
export SOPHIA_REDIS_URL="${SOPHIA_REDIS_URL:-redis://127.0.0.1:${REDIS_PORT}/0}"
export SOPHIA_DATABASE_URL="$PG_URL"

uv run uvicorn --factory sophia.api.app:create_standalone_api_app \
    --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!

SOPHIA_API_BASE_URL="http://127.0.0.1:${API_PORT}" \
SOPHIA_API_PROXY_TARGET="http://127.0.0.1:${API_PORT}" \
    pnpm -C frontend run dev -- --port "$WEB_PORT" --strictPort &
WEB_PID=$!

# Redis is a container, so it outlives the process group the harness kills.
# Stopping it here rather than in STOP_CMD keeps teardown to one mechanism: the
# group is killed, this trap fires, and nothing is left behind. If the group is
# killed outright the container survives, which is harmless — the guard above
# reuses a running one.
cleanup() {
    kill "$API_PID" "$WEB_PID" 2>/dev/null
    docker stop "$REDIS_NAME" >/dev/null 2>&1
}
trap cleanup EXIT INT TERM
wait -n "$API_PID" "$WEB_PID"
