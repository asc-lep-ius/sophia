# Sophia Phase 0 Deployment Guide

Sophia Phase 0 runs three application surfaces behind Caddy:

| Route | Upstream | Purpose |
|---|---|---|
| `/app/*` | `frontend:3000` | SvelteKit Phase 0 shell |
| `/api/*` | `api:8000` | FastAPI contract surface |
| `/legacy/*` | `sophia-gui:8080` | Transitional NiceGUI surface with prefix stripping |
| `/` | `sophia-gui:8080` | Legacy fallback while the strangler migration is active |

Only the proxy publishes ports in production. The API, frontend, Redis,
and NiceGUI containers stay on internal Compose networks.

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

## Postgres Backups And Restore Drills

Postgres is the only datastore the application reads or writes. Backups are not
considered done until the latest dump has been restored into an isolated scratch
database and that database proves Sophia's learning state is continuous.

Both `postgres` and `postgres-backup` are pinned by sha256 digest rather than by
the `18.4` tag, because a tag can be re-pushed and a storage engine that changes
underneath a running cluster is not a detail. `make deployment-policy` enforces
the pin.

### Backup Policy

The `postgres-backup` sidecar runs `pg_dump --format=custom --compress=9` on
`SOPHIA_BACKUP_INTERVAL_SECONDS` (default daily) and prunes dumps older than
`SOPHIA_BACKUP_RETENTION_DAYS` (default 14).

Custom format is used so a restore can be selective and parallel. `--no-sync` is
deliberately **not** passed: it lets `pg_dump` return before the dump is on
stable storage, which turns a backup into a promise rather than a file.

Dumps land on the `postgres-backups` volume. That volume is on the same host as
the database, so it survives a container loss but not a host loss. Ship the
dumps **encrypted off-host** — the volume alone is not a backup:

```bash
docker compose -f docker-compose.prod.yml exec postgres-backup \
  sh -c 'cat /backups/$(ls -t /backups | head -1)' \
  | age -r "$SOPHIA_BACKUP_AGE_RECIPIENT" \
  | aws s3 cp - "s3://$SOPHIA_BACKUP_BUCKET/sophia-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
```

### Backup Smoke Check

Run this after every deploy, and before starting a restore drill:

```bash
docker compose -f docker-compose.prod.yml ps postgres-backup
docker compose -f docker-compose.prod.yml exec postgres-backup ls -t /backups
curl -f https://sophia.example.com/api/metrics >/tmp/sophia-metrics.txt
grep -E "^(http_requests|web_vitals_reports|sse_connections_open)" /tmp/sophia-metrics.txt
```

Alert when the `postgres-backup` container exits, restarts repeatedly, or when
the postgres-backup service is unhealthy for more than five minutes. Treat each
of those states as stopped backups even if Docker restarts the container: the
healthcheck only proves a dump file exists, not that a recent one does, so check
the newest dump's timestamp against `SOPHIA_BACKUP_INTERVAL_SECONDS` before
calling the alert a false positive.

### Postgres Restore Drill

Run the quick backup smoke check weekly. Run the full restore drill monthly,
after every schema migration, and before promoting a new backup mechanism.
Record the source commit, dump timestamp, operator, and result in the deployment
log. The drill restores into a scratch database and never touches the live one:

```bash
make db.restore BACKUP_PATH=backups/sophia-20260828T020000Z.dump
```

That runs `pg_restore --exit-on-error` into `<database>_restore_drill`, compares
per-table row counts against the source, drops the scratch database, and prints
the elapsed restore time.

Capture the production learning-state fingerprint before the drill. The same
queries must match afterwards, except for rows written after the dump was taken:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "$SOPHIA_POSTGRES_USER" -d "$SOPHIA_POSTGRES_DB" <<'SQL'
SELECT COUNT(*) AS study_sessions FROM study_sessions;
SELECT COUNT(*) AS student_flashcards FROM student_flashcards;
SELECT COUNT(*) AS self_explanations FROM self_explanations;
SELECT COUNT(*) AS review_schedule FROM review_schedule;
SELECT COUNT(*) AS deadline_cache FROM deadline_cache;
SELECT COUNT(*) AS card_review_attempts FROM card_review_attempts;
SELECT MIN(next_review_at), MAX(next_review_at) FROM review_schedule;
SELECT MIN(due_at), MAX(due_at) FROM deadline_cache;
SELECT COUNT(score_at_last_review) FROM review_schedule;
SELECT MAX(last_reviewed_at), SUM(review_count) FROM review_schedule;
SELECT MAX(reviewed_at) FROM card_review_attempts;
SQL
```

The proof points are deliberately tied to user-visible learning continuity:

| Proof point | Tables and fields |
|---|---|
| Learning progress | `study_sessions`, `student_flashcards`, `self_explanations` |
| Due schedule | `review_schedule.next_review_at`, `deadline_cache.due_at` |
| Grade history | `card_review_attempts`, `review_schedule.score_at_last_review` |
| Review-event continuity | `review_schedule.last_reviewed_at`, `review_schedule.review_count`, `card_review_attempts.reviewed_at` |

`pg_restore --list` on the dump must name every table before the drill starts —
a dump that is short a table restores cleanly and proves nothing. Re-run the
fingerprint against the scratch database with `psql`, then confirm the live
service is still healthy:

```bash
pg_restore --list backups/sophia-20260828T020000Z.dump
curl -f https://sophia.example.com/api/ready
```

Record two numbers from each drill:

- **RTO** — the restore time the drill prints, plus the time to repoint the API.
  Budget: under 30 minutes for the current data volume.
- **RPO** — the backup interval, so at most
  `SOPHIA_BACKUP_INTERVAL_SECONDS` of writes are at risk. Default: 24 hours.
  Shorten the interval, or add WAL archiving, if that window is too wide.

A drill that does not restore learning-progress continuity fails: matching row
counts alone do not prove that `study_sessions`, `review_schedule`, and
`card_review_attempts` still describe the same learner history.

### Postgres Cutover Playbook

The cutover is the only step that can lose writes, so it stops them first.

1. **Stop writes.** Scale the writers to zero and leave the proxy serving a
   maintenance response:
   ```bash
   docker compose -f docker-compose.prod.yml stop api sophia-gui
   ```
2. **Confirm the rollback image still exists** before starting, because the
   import in step 7 is the point of no return:
   ```bash
   docker manifest inspect "${LOCAL_REGISTRY}/api:${PRE_CUTOVER_SHA}" >/dev/null
   ```
3. **Archive the SQLite file** before touching it. Copy the whole set — the
   `-wal` and `-shm` siblings hold committed transactions that `sophia.db`
   alone does not, and a container that was killed rather than stopped will
   have a non-empty WAL. Record the checksums; this copy is the only evidence
   left if the transfer is later disputed. Step 1 already stopped every prod
   writer, so nothing is mid-write here:
   ```bash
   docker run --rm -v sophia_sophia-data:/data:ro -v "$PWD:/out" alpine:3.20 \
     sh -c 'cp /data/sophia.db* /out/ && sha256sum /out/sophia.db* > /out/sophia-precutover.sha256'
   ```
4. **Give the host tooling a route to the database.** Steps 5-8 run `uv run`
   on the host — `scripts/sqlite_to_postgres.py` is not in the api image, only
   `src/` is — and they fall back to the `SOPHIA_DATABASE_URL` default of
   `localhost:5432`, which is not the production database. The prod `postgres`
   service only exposes 5432 on the internal `data` network, so publish it to
   the loopback interface for the duration of the cutover. Step 9 takes it
   away again:
   ```bash
   cat > /tmp/cutover-port.yml <<'YAML'
   services:
     postgres:
       ports:
         - "127.0.0.1:5432:5432"
   YAML
   docker compose -f docker-compose.prod.yml -f /tmp/cutover-port.yml up -d postgres
   export SOPHIA_DATABASE_URL="postgresql+asyncpg://${SOPHIA_POSTGRES_USER}:${SOPHIA_POSTGRES_PASSWORD}@127.0.0.1:5432/${SOPHIA_POSTGRES_DB}"
   ```
   Bind to `127.0.0.1`, never `0.0.0.0` — the database would otherwise be
   reachable from the network for as long as the cutover runs. Percent-encode
   the password if it contains `@ : / # ?`: the DSN is parsed as a URL, and an
   unescaped `@` resolves to a different host rather than failing.

5. **Migrate the schema:**
   ```bash
   make db.migrate
   ```
6. **Dry-run the transfer** and read the report before writing anything:
   ```bash
   make db.import SQLITE=/var/lib/docker/volumes/sophia_sophia-data/_data/sophia.db MODE=dry-run
   ```
7. **Import,** which copies every table, aligns the identity sequences, and
   verifies as it goes:
   ```bash
   make db.import SQLITE=... MODE=import
   ```
8. **Verify independently.** `scripts/sqlite_to_postgres.py --mode verify`
   re-reads both sides and compares row counts *and* per-table checksums. Row
   counts alone would pass a migration that silently nulled a column:
   ```bash
   make db.verify SQLITE=...
   ```
   A non-zero exit aborts the cutover. Restart the old stack and investigate.
9. **Restart writers** against Postgres, close the temporary route, and
   confirm readiness:
   ```bash
   unset SOPHIA_DATABASE_URL
   rm -f /tmp/cutover-port.yml
   docker compose -f docker-compose.prod.yml up -d postgres   # drops the published port
   docker compose -f docker-compose.prod.yml up -d api sophia-gui
   curl -f https://sophia.example.com/api/ready
   ```
   Confirm the port is gone before calling the cutover done — a forgotten
   `-f /tmp/cutover-port.yml` in a later `docker compose` invocation would put
   it back. Check the rendered port list, not `docker compose port`: that
   command exits 0 whether or not the port is published (it prints
   `invalid IP:0` when it is not), so it can never fail the check.
   ```bash
   docker compose -f docker-compose.prod.yml ps postgres --format '{{.Ports}}' \
     | grep -q -- '->' \
     && { echo "postgres is still published — remove the override, re-run step 9"; exit 1; }
   ```

**Rollback.** The application no longer contains a SQLite driver, so there is no
runtime fallback to fall back *to*: rolling back means redeploying the last
pre-cutover `IMAGE_TAG` against the archived snapshot from step 3, and
discarding whatever was written to Postgres after the cutover. That is a lossy
step, which is why steps 6 and 8 refuse to continue on a mismatch rather than
leaving it to be discovered later.

```bash
docker compose -f docker-compose.prod.yml down
docker run --rm -v sophia_sophia-data:/data -v "$PWD:/in" alpine:3.20 \
  sh -c 'cp /in/sophia.db* /data/ && chown 1000:1000 /data/sophia.db*'
IMAGE_TAG="$PRE_CUTOVER_SHA" docker compose -f docker-compose.prod.yml up -d
curl -f https://sophia.example.com/api/ready
```

Keep the archived snapshot and its checksums for one full release after cutover.
It is the evidence for any post-cutover discrepancy a learner reports, and the
input to the rollback above. Delete it only once a release has passed without
such a report.

## Operational Notes

- Keep `IMAGE_TAG` pinned to the full commit SHA that passed CI.
- Rotate `SOPHIA_SECRET_KEY_CURRENT` before sharing a production URL outside a
  trusted network.
- Keep the old NiceGUI route and tests until the Phase 1 two-process auth bridge
  and migrated frontend routes replace them deliberately.
- Use `docker compose -f docker-compose.prod.yml config` as the final local
  syntax gate before deployment.
