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
