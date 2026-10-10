#!/usr/bin/env bash
# Start the stack /ship step 2c walks, on loopback high ports.
#
# Runs in the foreground; the harness backgrounds it into its own process group
# and kills that group to stop it. Redis and the processing worker outlive the
# group, because they are containers — the EXIT trap below stops them.
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

# The processing worker (#128) runs as a container of its own compose project,
# scripts/stack/worker.yml, against the host's directories and this Postgres.
# Built before the walk, never here: `make docker-build-worker` takes minutes
# and would turn RUN_CMD's 10 s into a timeout. Without the image the stack
# still starts, and Process is refused with "no worker running".
WORKER_PROJECT="${SOPHIA_STACK_WORKER_PROJECT:-sophia-stack}"
WORKER_COMPOSE="$ROOT/scripts/stack/worker.yml"
WORKER_STARTED=0
start_worker() {
    if ! docker image inspect sophia-worker:latest >/dev/null 2>&1; then
        echo "sophia-worker:latest is not built — run \`make docker-build-worker\`;" \
             "processing will be refused until it is" >&2
        return
    fi
    export SOPHIA_STACK_DATA_DIR="${SOPHIA_DATA_DIR:-$HOME/.local/share/sophia}"
    export SOPHIA_STACK_CONFIG_DIR="${SOPHIA_CONFIG_DIR:-$HOME/.config/sophia}"
    export SOPHIA_STACK_CACHE_DIR="${SOPHIA_CACHE_DIR:-$HOME/.cache/sophia}"
    export SOPHIA_STACK_HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
    mkdir -p "$SOPHIA_STACK_DATA_DIR" "$SOPHIA_STACK_CACHE_DIR" "$SOPHIA_STACK_HF_HOME"
    # The one secret the worker needs, read from the same file SESSION_CMD
    # reads rather than sourced: the keyring variables beside it must not
    # reach a container that has no keyring backend.
    local env_file="${SOPHIA_ENV_FILE:-$SOPHIA_STACK_CONFIG_DIR/env}"
    if [[ -z "${SOPHIA_GEMINI_API_KEY:-}" && -r "$env_file" ]]; then
        SOPHIA_GEMINI_API_KEY="$(sed -n 's/^\(export \)\{0,1\}SOPHIA_GEMINI_API_KEY=//p' "$env_file" | tail -1)"
        export SOPHIA_GEMINI_API_KEY
    fi
    if nvidia-smi -L >/dev/null 2>&1; then
        export SOPHIA_STACK_GPU=all
    else
        # A driver the host itself cannot use (a kernel module older than the
        # libraries after an unattended upgrade, say) makes any container that
        # asks for the GPU fail to start at all. Start the worker without it:
        # it reports "no usable GPU", and that is what the learner is told.
        echo "nvidia-smi fails on the host; starting the worker without the GPU" \
             "so that Process is refused with that reason" >&2
        export SOPHIA_STACK_GPU=void
    fi
    docker compose -p "$WORKER_PROJECT" -f "$WORKER_COMPOSE" up -d --no-build worker >/dev/null \
        && WORKER_STARTED=1
}
start_worker

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
    # The worker first, and with a short timeout: the harness gives this trap
    # a few seconds before it kills the whole group, and the worker stops on
    # SIGTERM at once. A lecture mid-transcription is lost; each finished one
    # was committed.
    if [[ "$WORKER_STARTED" == 1 ]]; then
        docker compose -p "$WORKER_PROJECT" -f "$WORKER_COMPOSE" down --timeout 3 >/dev/null 2>&1
    fi
    docker stop "$REDIS_NAME" >/dev/null 2>&1
}
trap cleanup EXIT INT TERM
wait -n "$API_PID" "$WEB_PID"
