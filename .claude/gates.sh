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

# Measured on hephaestus, 2026-09-25, warm caches:
#   lint 8.0s · types 20.1s · tests 10.4s (365 tests) · total ~38s
# It was ~34s on 2026-09-12; the unit suite is what grew.
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

# The budget one full gate run is expected to fit in, in seconds. project-foreman
# prints `last · max · budget` from the past week's markers, advisory only. 60 is
# gate-lib's default and sits clear of the ~38s measured above, so a row that
# turns yellow means the gates really got slower, not that the line was drawn
# tight.
GATE_BUDGET_S=60

# Paths a tree change may skip the gates for. Empty, so nothing is skippable,
# because the obvious candidate is not inert here:
# frontend/tests/unit/paraglide-decision.test.ts reads
# docs/frontend-paraglide-decision.md, so docs/** is covered by TEST_CMD. Name a
# path only after checking that no gate reads it.
GATE_INERT_PATHS=""

# Python only. The frontend has its own formatter (prettier, via `pnpm lint`),
# but post-edit-lint.sh applies a single command to a single file, and one
# slot cannot serve both languages.
FORMAT_CMD="uv run ruff format"
LINT_FILE_CMD="uv run ruff check --fix"
FORMAT_EXTENSIONS="py"

# What decision-doc-context.sh treats as a product decision. The hook's fallback,
# `*SPEC*.md docs/decisions/** DECISIONS.md`, matched STUDY_SURFACE_SPEC.md and
# nothing in docs/, so the accepted records there (paraglide, form writes,
# charts, long-tail scope, NiceGUI retirement) could be rewritten inside a branch
# without the hook saying a word, which CLAUDE.md says it does. docs/** also
# matches run-contract-setup.md, which is a checklist. The hook only adds context,
# so that over-match costs one sentence, and a new record added to docs/ is
# covered without anyone having to remember this line.
DECISION_DOCS="*SPEC*.md docs/**"

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

# --- the pipeline this project pushes into ------------------------------------
# Who waits for the branch's pipeline, and for how long. **Nothing here runs a
# pipeline or changes what CI does** — these only say whether something is
# allowed to stand still watching one, and where that standing still happens.
#
# The wait used to sit inside the model's turn, at /ship step 9, which spent the
# rolling five-hour session window on a poll that produces no tokens: a
# fourteen-issue milestone burned roughly two hours of window on sophia's ~500s
# median pipeline and nearly four on tame-swarm's ~992s. `skills/milestone/run.sh`
# now does the waiting between issues, where wall clock is all it costs.
#
# CI_WAIT
#   always     wait for every phase's pipeline
#   tip-only   wait only for the branch that targets the default branch — the one
#              the stack collapses onto, and so the one whose pipeline is the
#              one standing between this work and master
#   never      never wait
# **Empty is `never`**, and deliberately: a project that never declared a
# pipeline is not one to be made to wait for one. A value that is none of the
# three is `never` too — a typo in this file must not hang a run for half an hour.
CI_WAIT="tip-only"

# How long that wait may take, in seconds, before it is recorded as a timeout.
# Empty or non-numeric is 1800. A timeout is recorded as a timeout and never
# resolves to green: "the pipeline passed" and "nothing ever watched a pipeline"
# reaching the reader as the same silence is the failure `parity=` already exists
# to end, and the milestone ledger's `pipeline=` field is that fix in the second
# place it was needed.
CI_WAIT_TIMEOUT=""

# The rest of the CI policy, and the reason it is declared here at all: a check
# skipped by policy and a check that passed reach a ledger as the same silence
# unless something writes the skip down at the moment it happens. Every `/ship`
# run prints `ci-policy=` beside the three gates and `parity=`, and it is written
# into `.claude/state/gates-<fingerprint>.ok` so the distinction outlives the
# turn. **Unset changes nothing anywhere** — a project with no block reads
# `ci-policy=unconfigured` and behaves exactly as it did before the key existed.
#
# CI_MR_SECONDS — the observed median MR pipeline, with the date it was measured.
# /project-setup writes it from this project's own pipeline history. Nothing
# reads it to decide anything; it is what a proposal to tier this project's CI
# has to argue against.
#   CI_MR_SECONDS="500  # median of the last 50 MR pipelines, 2026-09-18"
CI_MR_SECONDS="459  # median of 30 successful MR pipelines, 2026-09-25; was 489 over 26 on 2026-09-18"

# CI_IS_ONLY_GATE — yes | no. Is the pipeline the only thing checking this
# project? **Empty is `yes`**, and it is the one key here that fails closed: a
# project that has never declared a local gate is not one we may skip CI on. With
# `yes`, a configured skip is *refused* rather than applied, and the line says
# `refused (only-gate)` so that the refusal is visible rather than being a value
# that quietly did nothing.
#
# Left empty here, and the answer is genuinely mixed rather than obvious. The
# frontend has a real local gate -- TEST_CMD above runs 349 unit tests on every
# tree change. The backend does not: the full Python suite was deliberately kept
# off the Stop hook (see the note above TEST_CMD), so CI's `test:3.12` with its
# --cov-fail-under=85 is the only thing that runs it. Empty is `yes`, which is
# the safe half of that split, and it is inert either way while CI_TIER_PATHS is
# empty. Answer it properly before tiering anything.
CI_IS_ONLY_GATE=""

# CI_TIP_LABEL — the MR label that forces the full suite on a mid-stack branch,
# for the case the tiering did not anticipate. Empty is `full-ci`.
CI_TIP_LABEL=""

# CI_TIER_PATHS — the jobs or paths this project defers to the stack tip, named
# so the `ci-policy=` line can name them. Space-separated. Empty means nothing is
# deferred and every configured check ran, which is `ci-policy=full`.
#
# The line reads `tip-unknown` where a caller could not establish whether this
# branch is the tip — the Stop hook, which has no base to name. That is
# deliberate and it is `parity=pending`'s rule: "every configured check ran" is a
# claim, and a claim from an unresolved input is exactly the false all-clear this
# key exists to prevent. `/ship` always names a base, so a ship run resolves it.
#
# Setting this does not tier anything on its own: what CI runs is decided in
# `.gitlab-ci.yml`, and this is the declaration that lets a skip be recorded
# where somebody will read it. A skip nobody recorded is how a stale value once
# passed a Playwright suite over on a mid-stack phase, the ledger read all-green
# at 5am, and the broken flow rode the frozen branch to master.
#   CI_TIER_PATHS="playwright-e2e gpu-smoke"
# Empty because .gitlab-ci.yml defers nothing today. Tiering the three Playwright
# jobs to the stack tip is #112's explicit non-goal -- separate, and blocked on
# mipkovich/claude-config#36 -- so this project reads `ci-policy=unconfigured`
# and behaves exactly as it did before these keys existed.
CI_TIER_PATHS=""
