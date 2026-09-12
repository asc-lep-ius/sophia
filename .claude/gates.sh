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
#   lint ~7s · types ~20s · tests ~143s · total ~170s
LINT_CMD="uv run ruff check . && uv run ruff format --check . && pnpm -C frontend run lint"
TYPE_CMD="uv run pyright && pnpm -C frontend run check"

# TEST_CMD needs the Postgres container up (`make db.up`); it is declared
# `restart: unless-stopped`, so it survives a reboot. The suite is far more
# database-dependent than the `postgres` marker implies — only 11 files carry
# the marker, but with the container stopped 511 tests fail and 436 error,
# including ones under tests/unit. So there is no useful service-free subset
# to fall back to, and the full suite is what actually proves a change.
TEST_CMD="uv run pytest -q --tb=short && pnpm -C frontend run test:unit"

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
