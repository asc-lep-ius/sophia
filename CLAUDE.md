# Sophia

A study/learning system for TU Wien coursework. Two stacks in one repo: a
FastAPI + SQLModel backend and a SvelteKit frontend, fronted by Caddy.

## Layout

    src/sophia/
        api/            FastAPI app; routers/ is the HTTP surface, sessions.py the session record
        adapters/       outbound integrations — moodle (TUWEL), tiss, opencast, auth
        domain/         entities and errors
        infra/          di.py is the composition root; http, db, org_context
        services/       application logic
        cli/            cyclopts CLI — `sophia auth|db|lectures|plan|…`
        worker/         processing worker — claims ingestion jobs, runs the hermes stages in the CUDA image
    frontend/           SvelteKit; src/routes is the page surface, src/lib/components the shared UI
        tests/unit/     vitest — the Stop gate
        tests/e2e/      playwright — runs against a fixture, see gotchas
        messages/       inlang source strings; src/lib/paraglide/ is generated and gitignored
    tests/              python suite, needs Postgres
    docs/               accepted decision records — read before making a product decision
    proxy/              Caddyfile: / → /app/, /app/* → frontend:3000, /api/* → api:8000

## Commands

Gate commands and their measured timings live in `.claude/gates.sh`; that file is
the source of truth and explains why each one is scoped the way it is.

    uv run ruff check . && uv run ruff format --check . && pnpm -C frontend run lint
    uv run pyright && pnpm -C frontend run check      # 1453 files, 0 errors
    pnpm -C frontend run test:unit                    # 349 tests, ~11s — the Stop gate
    make test                                         # full python suite, ~143s, needs Postgres
    make db.up                                        # local Postgres only
    make docker-build-worker                          # sophia-worker:latest, needed before Process works

The full Python suite is deliberately *not* a Stop gate: at 143s a headless
`/ship` turn backgrounds it and then ends the turn waiting for a notification
that cannot arrive. CI runs it with `--cov-fail-under=85` instead.

## Gotchas

**The API cannot start until somebody has logged in on this box once.**
`create_app` (`src/sophia/infra/di.py`) raises `AuthError("Not logged in — run:
sophia auth login")` when there is no stored session and nothing stored to log
in with. Verified 2026-09-18: uvicorn exits at lifespan startup.

That is a first-run cost only if the first login stores the TOTP secret. MFA has
been mandatory since 2026-04-01, so a password alone can never log in again.
`sophia auth login --save-credentials` stores the password and the TOTP secret;
from then on `ensure_valid_session` (`src/sophia/services/job_runner.py`) and
`create_app` log in again with a generated code when the session has died, and
the API's keepalive pings TUWEL and TISS every 300 s (#124). Without the secret,
a session that idles out (TUWEL: 8 h) needs a person with an authenticator.

On a headless box neither prerequisite holds by default — the config dir must be
writable, and the TOTP secret is refused unless `PYTHON_KEYRING_BACKEND` pins a
backend that is not plaintext. `docs/run-contract-setup.md` is the per-box
checklist; the deployed container's version of the same gap is #111.

The credential coupling is shallow: `creds` is used only to cookie the shared
http session and to build `MoodleAdapter` (`_init_resources` in `di.py`); the engine,
migrations, TISS, Opencast and the downloader need none of it. Nothing in CI has
ever started the product — `.gitlab-ci.yml` runs Postgres as a service for
database-backed tests and no job launches the API or the frontend.

**The e2e suite tests a double, not the server.** `playwright.config.ts:18`
starts `tests/e2e/fixture-api.mjs` as its webServer, and nothing pins that
fixture's answers to the real API's. `assert-api-client-contract.mjs` pins the
*client's* call sites to the generated OpenAPI types and says nothing about
response parity. The fixture returned 200 for attempts the real server refused
with 412, and forty green tests said nothing was wrong (#98). Treat a passing
study-surface e2e test as evidence about the fixture until a parity suite exists.

**`SOPHIA_E2E_AUTH=1` plus the `sophia-e2e-auth` cookie**
(`frontend/src/hooks.server.ts:33`) bypasses sign-in entirely, and
`tests/e2e/shell-auth.ts` hardcodes a numeric `sophia-learning-path-id`. That
seeded id is why #106 went unnoticed: a real login got the non-numeric sentinel
`"default-learning-path"`, which every consumer coerces with `Number()` to `NaN`.
Never use this path to demonstrate that a flow works.

**`uv` and `pnpm` live in `~/.local/bin`**, which is on a login shell's PATH but
not on the one a hook inherits. `.claude/gates.sh` exports it for that reason.

**`frontend/src/lib/paraglide/` is generated output.** Run
`pnpm -C frontend run paraglide:compile` after changing `messages/`; most
frontend scripts chain it already. Do not edit the generated directory.

**Do not `docker compose up` from this repo on hephaestus.** Ports 80/443 are
held by the homelab Caddy that fronts `gitlab.hephaestus`, and 5432 by the
long-running `sophia-postgres-1`. `docker compose down` here would stop that
Postgres. Use loopback high ports for anything local.

## Decisions

`docs/` holds accepted decision records, and they bind. `frontend-paraglide-decision.md`
already settles UI locale precedence — Paraglide cookie, then browser preference,
then base locale `en`, with `sophia-locale` as a compatibility alias — so that is
not an open question. Rewriting a decision doc inside an implementation branch is
a product fork, not an edit; `.claude/hooks/decision-doc-context.sh` will say so.
