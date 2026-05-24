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

Run the same gates CI uses before shipping configuration changes:

```bash
make test
make lint
make typecheck
uv run pytest tests/api/ -q
uv run python scripts/blocking_audit.py --check
make openapi.check
pnpm -C frontend run lint
pnpm -C frontend run check
pnpm -C frontend run test:unit
pnpm -C frontend run size-limit
pnpm -C frontend run test:e2e -- a11y.spec.ts de-overflow.spec.ts
docker compose config
docker compose -f docker-compose.prod.yml config
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

## Proxy Notes

[proxy/Caddyfile](proxy/Caddyfile) enables JSON access logs and configures
Caddy servers for HTTP/1.1, HTTP/2, and HTTP/3. Publish UDP `443` and set
`SOPHIA_SITE_ADDRESS` to an HTTPS site address for HTTP/3 clients.

The SSE matcher sends event-stream paths to the API with `flush_interval -1`
and disables upstream response compression. The site intentionally does not
enable the Caddy `encode` directive so event streams are not buffered or
compressed by the proxy.

`/api/auth/login` has a reserved rate-limit comment only. Do not enable an
active rate-limit directive until the Caddy image is replaced by a build that
contains the required plugin.

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
  syntax gate before deployment.# Sophia GUI — Deployment Guide

## Quick Start

```bash
# Start the GUI service
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Stop
docker compose down
```

The GUI is available at `http://localhost:8080` by default.

To use a different port, set `SOPHIA_GUI_PORT` in your `.env` file or environment:

```bash
SOPHIA_GUI_PORT=9090 docker compose up -d
```

---

## Remote Access

Sophia binds to `127.0.0.1` by default. To access it from another machine,
pick **one** of the following approaches.

### Tailscale / WireGuard (Recommended)

Install [Tailscale](https://tailscale.com/) or WireGuard on both machines.
The GUI is then reachable via your Tailscale IP without exposing it to the
public internet.

```bash
# No config changes needed — just connect via Tailscale IP
http://100.x.y.z:8080
```

### Caddy Reverse Proxy

[Caddy](https://caddyserver.com/) provides automatic HTTPS.

Example `Caddyfile`:

```caddyfile
sophia.example.com {
    reverse_proxy localhost:8080
}
```

```bash
caddy run --config Caddyfile
```

### SSH Tunnel

Forward the port over SSH for ad-hoc access:

```bash
ssh -L 8080:localhost:8080 user@remote-host
# Then open http://localhost:8080 locally
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SOPHIA_GUI_HOST` | `127.0.0.1` | Bind address for the GUI server |
| `SOPHIA_GUI_PORT` | `8080` | Port for the GUI server |
| `SOPHIA_DATA_DIR` | Platform default | Directory for SQLite DB and data files |
| `SOPHIA_LOG_FORMAT` | `console` | Log format: `console` or `json` |
| `SOPHIA_GUI_SECRET` | `sophia-gui-storage` | NiceGUI storage secret (see known limitations) |

---

## Security Notes

- **Default binding is `127.0.0.1`** — the GUI is not accessible from the
  network unless you explicitly bind to `0.0.0.0` or use a reverse proxy.
- **Sophia is a single-user tool.** There is no authentication layer. Rely on
  the network layer (VPN, SSH tunnel, firewall) to restrict access.
- **Do not expose the GUI to the public internet** without a reverse proxy
  that handles TLS and authentication.

---

## Monitoring

### Health Endpoints

| Endpoint | Description |
|---|---|
| `/health` | Returns 200 when the server is running |
| `/ready` | Returns 200 when the app is fully initialized |

### Docker Healthcheck

The `docker-compose.yml` includes a healthcheck that polls `/health`
every 30 seconds. Check container health:

```bash
docker inspect --format='{{.State.Health.Status}}' sophia-sophia-gui-1
```

### Log Format

Set `SOPHIA_LOG_FORMAT=json` for structured JSON logs suitable for log
aggregation tools. The default `console` format is human-readable.

---

## Known Limitations

- **`storage_secret` is hardcoded** — NiceGUI's `storage_secret` is set to a
  static value (`sophia-gui-storage`). This is acceptable for a single-user
  tool but means session cookies are predictable. Set `SOPHIA_GUI_SECRET` to
  override if needed.
- **No authentication layer** — access control relies entirely on the network
  layer. Use Tailscale, SSH tunnels, or a reverse proxy with auth.
- **Single-instance only** — the SQLite backend does not support concurrent
  writes from multiple GUI instances.
