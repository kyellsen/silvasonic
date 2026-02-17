# Port Allocation

All Silvasonic services use a consistent port scheme. Ports are configured via `.env`.

## Port Table

| Service               | Internal Port | Host Port (Dev) | `.env` Variable                 |
| --------------------- | ------------- | --------------- | ------------------------------- |
| **TimescaleDB**       | 5432          | 5432            | `SILVASONIC_DB_PORT`            |
| **Controller**        | 9100          | 9100            | `SILVASONIC_CONTROLLER_PORT`    |
| **Recorder** (Health) | 9500          | —               | — (internal only)               |
| Gateway (Caddy) HTTP  | 80            | 80              | `SILVASONIC_GATEWAY_HTTP_PORT`  |
| Gateway (Caddy) HTTPS | 443           | 443             | `SILVASONIC_GATEWAY_HTTPS_PORT` |

> **Note:** Tailscale creates a VPN overlay — no dedicated ports needed.

## Principles

1. **Standard ports** for well-known services (PostgreSQL 5432, HTTP 80/443)
2. **`91XX` range** for Silvasonic service APIs (Controller)
3. **`9500`** unified internal health port for services without their own API
4. All host-exposed ports configurable via `.env`

## Health Port Convention

- Services **with an API** (Controller): Health is a route on the API port (`/healthy` on `9100`)
- Services **without an API** (Recorder): Use `silvasonic.core.health` on default port `9500`
- Compose health checks run **inside** the container — no host port needed
- Multiple recorder instances can all use `9500` internally (container isolation)

## Production vs. Development

- **Production**: Only Caddy exposes ports (80/443). All other services communicate via the internal `silvasonic-net` Podman network.
- **Development**: Controller exposed on localhost:9100 for debugging. Recorder has no host port.
