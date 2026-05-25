# Sophia Phase 0 Deployment Guide

Sophia Phase 0 runs three application surfaces behind Caddy:

| Route | Upstream | Purpose |
|---|---|---|
| `/app/*` | `frontend:3000` | SvelteKit Phase 0 shell |
| `/api/*` | `api:8000` | FastAPI contract surface |
| `/legacy/*` | `sophia-gui:8080` | Transitional NiceGUI surface with prefix stripping |
| `/` | `sophia-gui:8080` | Legacy fallback while the strangler migration is active |

Only the proxy publishes ports in production. The API, frontend, Redis,
NiceGUI, and litestream containers stay on internal Compose networks.

## Local Validation

Run the same gates CI uses before shipping proxy, compose, frontend contract,
and deployment changes:

```bash
uv run pytest tests/api/test_proxy_config.py -q
make blocking-audit
make openapi.check
make frontend.check
make frontend.a11y
make docker-validate
make lint
make typecheck
```

## Development Compose

```bash
docker compose up -d proxy frontend api redis sophia-gui
docker compose ps
docker compose logs -f proxy api frontend sophia-gui
```

Useful endpoints:

| Endpoint | Expected role |
|---|---|
| `http://localhost/api/health` | API liveness |
| `http://localhost/api/ready` | API readiness gate polled by Docker healthchecks |
| `http://localhost/app/` | SvelteKit app shell |
| `http://localhost/legacy/` | NiceGUI legacy surface |
| `http://localhost/` | Legacy fallback |

The old direct GUI workflow remains available on `SOPHIA_GUI_PORT`, defaulting
to `8080`, so existing GUI and GPU profiles keep working.

## Production Compose

Production uses commit-pinned images from the local registry. Do not deploy
`:latest` tags.

```bash
export LOCAL_REGISTRY=gitlab.hephaestus:5050/mipkovich/sophia
export IMAGE_TAG=<commit-sha>
export SOPHIA_SITE_ADDRESS=https://sophia.example.com
export SOPHIA_FRONTEND_ORIGIN=https://sophia.example.com
export SOPHIA_SECRET_KEY_CURRENT=<32+ byte random secret>

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml ps
```

`proxy` is the only production service with published ports. Leave the app and
data networks internal unless a later phase explicitly changes the topology.

## Frontend Origin And Forwarded Headers

The SvelteKit frontend uses `adapter-node` behind Caddy. Both Compose files set
these environment variables on the `frontend` service:

| Variable | Value | Purpose |
|---|---|---|
| `ORIGIN` | `SOPHIA_FRONTEND_ORIGIN` | Public origin accepted by SvelteKit |
| `PROTOCOL_HEADER` | `x-forwarded-proto` | Trust Caddy's external request scheme |
| `HOST_HEADER` | `x-forwarded-host` | Trust Caddy's external request host |

Caddy forwards `X-Forwarded-Proto` and `X-Forwarded-Host` in
[proxy/Caddyfile](proxy/Caddyfile). Keep `SOPHIA_SITE_ADDRESS` and
`SOPHIA_FRONTEND_ORIGIN` aligned to the same external origin so browser fetches,
SSR loads, cookies, and redirects all resolve through the proxy.

## Proxy Notes

[proxy/Caddyfile](proxy/Caddyfile) enables JSON access logs and configures
Caddy servers for HTTP/1.1, HTTP/2, and HTTP/3. Publish UDP `443` and set
`SOPHIA_SITE_ADDRESS` to an HTTPS site address for HTTP/3 clients.

The SSE matcher handles `/api/events*`, `/api/*/events*`, and `/api/*/stream*`
before the generic `/api/*` route. It sends event-stream paths to the API with
`flush_interval -1` and disables upstream response compression. The site
intentionally does not enable the Caddy `encode` directive so event streams are
not buffered or compressed by the proxy.

`/api/auth/login` is actively rate limited at the Caddy edge by the
`caddy-ratelimit` plugin. The current policy allows five POST attempts per
minute per remote IP, groups IPv6 clients by /64 prefix, and applies jitter to
avoid synchronized retries. Keep the proxy image built from
[proxy/Dockerfile](proxy/Dockerfile) so the custom Caddy binary includes the
plugin before deploying Caddyfile changes.

## CI Merge Gates

GitLab CI keeps the Python gates (`lint`, `typecheck`, `test:3.12`,
`openapi-check`, `blocking-audit`, `compose-config`) and the frontend gates
(`frontend-check`, `frontend-lint`, `frontend-unit`, `frontend-size`,
`frontend-a11y`) in the blocking `check` stage. The explicit
`frontend-contract-guards` job runs the package contract, server-fetch guard,
OpenAPI types guard, and API client guard by name so Phase 0 contract drift is
visible in the merge gate.

## Secret-Key Rotation

Phase 0 validates that production has a signing key but does not add real auth
or persistent settings.

1. Generate a new high-entropy secret and set it as `SOPHIA_SECRET_KEY_CURRENT`.
2. Move the old current value to `SOPHIA_SECRET_KEY_PREVIOUS`.
3. Deploy all containers with the same pair of values.
4. Wait longer than the maximum signed-session lifetime used by the deployment.
5. Remove `SOPHIA_SECRET_KEY_PREVIOUS` and deploy again.

Never commit real secret values. Keep them in the deployment environment or a
secret manager.

## Health And Readiness

| Component | Check |
|---|---|
| Proxy | `curl -f https://sophia.example.com/api/health` |
| API | Docker healthcheck polls `http://localhost:8000/api/ready` |
| Frontend | Docker healthcheck polls `http://localhost:3000/app/` |
| NiceGUI | Docker healthcheck polls `http://localhost:8080/ready` |
| Redis | `redis-cli ping` |

The API readiness endpoint is deliberately stricter than liveness. A `503`
means the container is reachable but one of the readiness checks has not been
marked ready by the current phase's lifecycle wiring.

## Litestream Backups And Restore Drills

The production compose file includes a `litestream/litestream:0.5.11` sidecar
wired to the read-only `sophia-data` volume. Backups are not considered done
until the latest replica has been restored into an isolated volume and the
restored database proves that Sophia's learning state is continuous.

Configure these variables before enabling the sidecar:

| Variable | Purpose |
|---|---|
| `LITESTREAM_REPLICA_URL` | Destination, for example `s3://bucket/path/sophia.db` |
| `LITESTREAM_ACCESS_KEY_ID` | Object-store access key |
| `LITESTREAM_SECRET_ACCESS_KEY` | Object-store secret key |
| `LITESTREAM_REGION` | Object-store region, default `auto` |
| `LITESTREAM_ENDPOINT` | Optional S3-compatible endpoint |

### Replica Smoke Check

Run this after every deploy and before starting a restore drill:

```bash
docker compose -f docker-compose.prod.yml ps litestream
docker compose -f docker-compose.prod.yml logs litestream
docker compose -f docker-compose.prod.yml exec litestream litestream snapshots "$LITESTREAM_REPLICA_URL"
curl -f https://sophia.example.com/api/metrics >/tmp/sophia-metrics.txt
grep -E "^(http_requests|web_vitals_reports|sse_connections_open)" /tmp/sophia-metrics.txt
```

Alert when the `litestream` container exits, restarts repeatedly, or when the
litestream service is unhealthy for more than five minutes. Treat each of those
states as stopped replication even if Docker restarts the container. The first
response is to run `litestream snapshots`, inspect the sidecar logs, and verify
that the current `LITESTREAM_REPLICA_URL` still accepts writes.

### Restore Drill Cadence

Run the quick `litestream snapshots` validation weekly. Run the full isolated
restore drill monthly, after every schema migration, after changing
`LITESTREAM_REPLICA_URL`, and before promoting a new backup mechanism. Record
the source commit, source snapshot timestamp, restored snapshot timestamp,
operator, and result in the deployment log.

### Restore Drill

Capture the production learning-state fingerprint before the drill. The same
queries must match after restore, except for rows intentionally written after
the selected snapshot timestamp.

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps --entrypoint python api <<'PY'
import sqlite3

queries = [
    "PRAGMA integrity_check;",
    "SELECT COUNT(*) AS study_sessions FROM study_sessions;",
    "SELECT COUNT(*) AS student_flashcards FROM student_flashcards;",
    "SELECT COUNT(*) AS self_explanations FROM self_explanations;",
    "SELECT COUNT(*) AS review_schedule FROM review_schedule;",
    "SELECT COUNT(*) AS deadline_cache FROM deadline_cache;",
    "SELECT COUNT(*) AS card_review_attempts FROM card_review_attempts;",
    "SELECT MIN(next_review_at), MAX(next_review_at) FROM review_schedule;",
    "SELECT MIN(due_at), MAX(due_at) FROM deadline_cache;",
    "SELECT COUNT(score_at_last_review) FROM review_schedule;",
    "SELECT MAX(last_reviewed_at), SUM(review_count) FROM review_schedule;",
    "SELECT MAX(reviewed_at) FROM card_review_attempts;",
]
with sqlite3.connect("/data/sophia.db") as db:
    for query in queries:
        print(query, db.execute(query).fetchall())
PY
```

The proof points are deliberately tied to user-visible learning continuity:

| Proof point | Tables and fields |
|---|---|
| Learning progress | `study_sessions`, `student_flashcards`, `self_explanations` |
| Due schedule | `review_schedule.next_review_at`, `deadline_cache.due_at` |
| Grade history | `card_review_attempts`, `review_schedule.score_at_last_review` |
| Review-event continuity | `review_schedule.last_reviewed_at`, `review_schedule.review_count`, `card_review_attempts.reviewed_at` |

Restore into a temporary volume. Do not restore over the production volume as
part of a drill.

```bash
docker volume create sophia_restore_drill
docker run --rm \
  -e LITESTREAM_ACCESS_KEY_ID \
  -e LITESTREAM_SECRET_ACCESS_KEY \
  -e LITESTREAM_REGION \
  -e LITESTREAM_ENDPOINT \
  -v sophia_restore_drill:/data \
  litestream/litestream:0.5.11 \
  restore -if-replica-exists -o /data/sophia.db "$LITESTREAM_REPLICA_URL"

docker run --rm -v sophia_restore_drill:/data alpine:3.20 \
  sh -c "apk add --no-cache sqlite >/dev/null && sqlite3 /data/sophia.db \
    'PRAGMA integrity_check;' \
    'SELECT COUNT(*) AS study_sessions FROM study_sessions;' \
    'SELECT COUNT(*) AS student_flashcards FROM student_flashcards;' \
    'SELECT COUNT(*) AS self_explanations FROM self_explanations;' \
    'SELECT COUNT(*) AS review_schedule FROM review_schedule;' \
    'SELECT COUNT(*) AS deadline_cache FROM deadline_cache;' \
    'SELECT COUNT(*) AS card_review_attempts FROM card_review_attempts;' \
    'SELECT MIN(next_review_at), MAX(next_review_at) FROM review_schedule;' \
    'SELECT MIN(due_at), MAX(due_at) FROM deadline_cache;' \
    'SELECT COUNT(score_at_last_review) FROM review_schedule;' \
    'SELECT MAX(last_reviewed_at), SUM(review_count) FROM review_schedule;' \
    'SELECT MAX(reviewed_at) FROM card_review_attempts;'"

docker volume rm sophia_restore_drill
curl -f https://sophia.example.com/api/ready
```

The `PRAGMA integrity_check` result must be `ok`. The restored counts and
timeline extrema must match the saved fingerprint for the chosen snapshot. If a
field is missing, the drill fails because the restored database does not yet
prove the learning progress, due schedule, grade history, and review-event
continuity required by Phase 4.

## Operational Notes

- Keep `IMAGE_TAG` pinned to the full commit SHA that passed CI.
- Rotate `SOPHIA_SECRET_KEY_CURRENT` before sharing a production URL outside a
  trusted network.
- Keep the old NiceGUI route and tests until the Phase 1 two-process auth bridge
  and migrated frontend routes replace them deliberately.
- Use `docker compose -f docker-compose.prod.yml config` as the final local
  syntax gate before deployment.
