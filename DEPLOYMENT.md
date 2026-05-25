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

## Litestream Backup Stub

The production compose file includes a litestream sidecar wired to the
`sophia-data` volume. Configure these variables before enabling it:

| Variable | Purpose |
|---|---|
| `LITESTREAM_REPLICA_URL` | Destination, for example `s3://bucket/path/sophia.db` |
| `LITESTREAM_ACCESS_KEY_ID` | Object-store access key |
| `LITESTREAM_SECRET_ACCESS_KEY` | Object-store secret key |
| `LITESTREAM_REGION` | Object-store region, default `auto` |
| `LITESTREAM_ENDPOINT` | Optional S3-compatible endpoint |

Backup smoke check:

```bash
docker compose -f docker-compose.prod.yml logs litestream
docker compose -f docker-compose.prod.yml exec litestream litestream snapshots "$LITESTREAM_REPLICA_URL"
```

Restore drill:

```bash
docker compose -f docker-compose.prod.yml down
docker run --rm \
  -e LITESTREAM_ACCESS_KEY_ID \
  -e LITESTREAM_SECRET_ACCESS_KEY \
  -e LITESTREAM_REGION \
  -e LITESTREAM_ENDPOINT \
  -v sophia_sophia-data:/data \
  litestream/litestream:0.3.13 \
  restore -if-replica-exists -o /data/sophia.db "$LITESTREAM_REPLICA_URL"
docker compose -f docker-compose.prod.yml up -d
curl -f https://sophia.example.com/api/ready
```

Run a restore drill after first production deployment and after changing the
replica destination.

## Operational Notes

- Keep `IMAGE_TAG` pinned to the full commit SHA that passed CI.
- Rotate `SOPHIA_SECRET_KEY_CURRENT` before sharing a production URL outside a
  trusted network.
- Keep the old NiceGUI route and tests until the Phase 1 two-process auth bridge
  and migrated frontend routes replace them deliberately.
- Use `docker compose -f docker-compose.prod.yml config` as the final local
  syntax gate before deployment.
