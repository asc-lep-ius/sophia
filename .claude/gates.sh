# Per-project quality gate commands. Anything left empty is skipped.
# Sourced by .claude/hooks/gate-lib.sh and read by /ship.
#
# This repo is two stacks — a FastAPI/SQLModel backend and a SvelteKit
# frontend — and both are gated, because most of the Frontend Pivot milestone
# touches only the latter. Each slot chains the backend command first, then
# the frontend one, so a failure names which stack broke.
#
# uv and pnpm live in ~/.local/bin, which is on the PATH of a login shell but
# not of the non-login shell a hook can inherit. Setting it here rather than
# relying on the caller's environment is deliberate: a gate that cannot find
# its own tools fails every turn and reads as "your code is broken".
export PATH="$HOME/.local/bin:$PATH"

# Measured on hephaestus, 2026-09-12, warm caches:
#   lint ~7s · types ~20s · tests ~7s · total ~34s
LINT_CMD="uv run ruff check . && uv run ruff format --check . && pnpm -C frontend run lint"
TYPE_CMD="uv run pyright && pnpm -C frontend run check"

# Frontend tests only, and the total gate stays under ~35s. That ceiling is the
# point, not an accident.
#
# The full Python suite was tried here first and had to be removed. It takes
# 143s, and a /ship turn running headless (`claude -p`, as the milestone runner
# invokes it) reliably pushes a command that long into the background and then
# ends the turn waiting for a notification that cannot arrive — the process is
# gone. That killed two consecutive attempts to ship #103 at step 2, both times
# with the work already committed and reviewed.
#
# The backend is not ungated, it is gated one step later: CI's `test:3.12` job
# runs the whole suite with `--cov-fail-under=85` on every push, and /ship's
# last step triages that pipeline. `pyright` above still covers the backend
# statically, in-turn.
#
# Note the two are not identical: no coverage floor is enforced here, only in
# CI. Coverage was 91.70% at the last full run.
#
# If you restore the Python suite, raise the Stop hook timeout in
# settings.json to match — and expect headless /ship turns to start failing.
TEST_CMD="pnpm -C frontend run test:unit"

# Python only. The frontend has its own formatter (prettier, via `pnpm lint`),
# but post-edit-lint.sh applies a single command to a single file, and one
# slot cannot serve both languages.
FORMAT_CMD="uv run ruff format"
LINT_FILE_CMD="uv run ruff check --fix"
FORMAT_EXTENSIONS="py"

# Opt-in only, never part of run_all_gates. Left unset until someone picks the
# modules worth mutating — scoring, scheduling and the authorisation guards are
# the branchy, deterministic candidates.
MUTATION_CMD=""
MUTATION_PATHS=""

# --- The run contract ---------------------------------------------------------
# None of these is a gate. Nothing below ever runs on Stop; /ship step 2c reads
# them to start the product and walk a flow on it.
#
# The whole contract is box-local, because Sophia cannot start until somebody has
# logged in on the machine once: `create_app` (src/sophia/infra/di.py:64) loads a
# stored TUWEL session and raises AuthError before it builds anything. After that
# first login, `ensure_valid_session` re-authenticates from the keyring with no
# MFA code, so every run after it is unattended. docs/run-contract-setup.md is
# the per-box checklist; the deployed container's version of the gap is #111.
#
# Ports and the Redis URL are exported rather than hardcoded twice: SESSION_CMD
# runs in a fresh shell and must mint into the same Redis the stack reads, or the
# cookie it prints verifies against nothing.
export SOPHIA_STACK_API_PORT=8001
export SOPHIA_STACK_WEB_PORT=5173
export SOPHIA_STACK_REDIS_PORT=16379
export SOPHIA_REDIS_URL="redis://127.0.0.1:16379/0"

# Loopback dev servers, not `docker compose up`: on hephaestus ports 80 and 443
# belong to the homelab Caddy that fronts gitlab.hephaestus, and 5432 to the
# long-running dev Postgres that a `docker compose down` here would stop.
# Postgres is assumed already up (`make db.up`) and is never started or stopped
# by the harness for the same reason.
# Measured 2026-09-18: RUN_CMD to READY_URL 2.5s, SESSION_CMD 1.4s, STOP_CMD 0.4s.
# Allow ~25s on a cold database instead — alembic runs the migrations on boot.
RUN_CMD="scripts/run_stack.sh"

# Empty on purpose: teardown is one mechanism, not two. The harness kills the
# process group it started, which covers uvicorn and vite, and run_stack.sh traps
# that to stop its Redis container as well. A STOP_CMD that only stopped Redis
# would leave the stack up and read as a failure, which is how this was found.
STOP_CMD=""

# Through the frontend, not straight at the API: this one URL proves vite is up,
# its /api proxy is wired, and the API behind it is ready. It is also the origin
# the browser uses, which is what the __Host- session cookie requires.
READY_URL="http://127.0.0.1:5173/api/ready"

# A project mint script — the third path project-setup names, alongside a test
# authenticator override and a seeded row. It calls sophia's own
# `ensure_valid_session` (src/sophia/services/job_runner.py), so an expired
# session is refreshed from the keyring without MFA, then writes a real session
# record and prints its cookie. It carries the operator's real TUWEL and TISS
# session on purpose: a faked identity lands in an empty workspace, because
# course_materials, lecture_modules and topic_mappings stay empty until a TUWEL
# sync has run, so it could not exercise the study surface at all.
#
# It reads ~/.config/sophia/env itself rather than relying on a sourced profile,
# because this runs in an environment that has never sourced anything. That is
# also why SOPHIA_KEYRING_PASSWORD is not exported anywhere: only the one script
# that needs it ever holds it. See docs/run-contract-setup.md.
#
# The harness reads no secret: the keyring touch is inside the project's own
# code, where job_runner already does it, and this line names no credential
# store. What it costs is that the proof walk is box-bound — it works where
# somebody has logged in once, and cannot work in CI or on a fresh clone. That is
# the accepted trade, recorded here rather than rediscovered later.
#
# Never SOPHIA_E2E_AUTH=1 plus the `sophia-e2e-auth` cookie
# (frontend/src/hooks.server.ts:33): that skips the server's own session record
# and is the proof theatre step 2c exists to refuse.
SESSION_CMD="uv run python scripts/mint_session.py"

# The surface this project is answerable for. Routers are here because a diff
# that moves or deletes a route moves the surface just as a page does.
# frontend/messages/** is deliberately out: a translated string does change what
# the user reads, but putting it here would demand a browser walk for every copy
# fix. Revisit if a copy change ever ships broken.
SURFACE_PATHS="frontend/src/routes/** frontend/src/lib/components/** frontend/src/lib/i18n/** src/sophia/api/routers/**"

# Empty, and this one is a finding rather than an absence. The whole e2e suite
# runs against a double — playwright.config.ts:18 starts tests/e2e/fixture-api.mjs
# as its webServer — and nothing holds that double to the real server. The
# existing guards pin the *client*: assert-api-client-contract.mjs checks the
# frontend calls the generated OpenAPI client instead of hand-rolled casts. It
# says nothing about whether the fixture's answers match the server's. Searched
# for pact/schemathesis/msw and found only chronos-date-parity, which is
# Python-to-TypeScript date maths. Until something pins it, every study-surface
# e2e test is a test of fixture-api.mjs: it returned 200 for the attempts the
# real server refused with 412, and forty green tests said nothing was wrong.
PARITY_CMD=""
PARITY_PATHS=""
