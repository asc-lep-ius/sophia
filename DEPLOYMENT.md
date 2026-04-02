# Sophia GUI — Deployment Guide

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
