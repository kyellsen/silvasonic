# Port Allocation

All Silvasonic services use a consistent port scheme. Ports are configured via `.env`.

## Port Table

| Service                | Internal Port | Host Port (Dev) | `.env` Variable                 | Status         |
| ---------------------- | ------------- | --------------- | ------------------------------- | -------------- |
| **TimescaleDB**        | 5432          | 5432            | `SILVASONIC_DB_PORT`            | ✅ Implemented  |
| **Redis**              | 6379          | 6379            | `SILVASONIC_REDIS_PORT`         | 📋 Planned v0.2 |
| **Controller**         | 9100          | 9100            | `SILVASONIC_CONTROLLER_PORT`    | ✅ Implemented  |
| **Processor**          | 9200          | —               | `SILVASONIC_PROCESSOR_PORT`     | 📋 Planned v0.5 |
| **Web-Interface**      | 8000          | 8000            | `SILVASONIC_WEBUI_PORT`         | 📋 Planned v0.8 |
| **Recorder** (Health)  | 9500          | —               | — (internal only)               | ✅ Scaffold     |
| **BirdNET** (Health)   | 9500          | —               | — (internal only)               | 📋 Planned v1.1 |
| **BatDetect** (Health) | 9500          | —               | — (internal only)               | 📋 Planned v1.3 |
| **Uploader** (Health)  | 9500          | —               | — (internal only)               | 📋 Planned v0.6 |
| **Weather** (Health)   | 9500          | —               | — (internal only)               | 📋 Planned v1.2 |
| Gateway (Caddy) HTTP   | 80            | 80              | `SILVASONIC_GATEWAY_HTTP_PORT`  | 📋 Planned v0.7 |
| Gateway (Caddy) HTTPS  | 443           | 443             | `SILVASONIC_GATEWAY_HTTPS_PORT` | 📋 Planned v0.7 |
| **Icecast**            | 8000          | 8080            | `SILVASONIC_ICECAST_PORT`       | 📋 Planned v0.9 |

> **Note:** Tailscale creates a VPN overlay — no dedicated ports needed.

## Principles

1. **Standard ports** for well-known services (PostgreSQL 5432, HTTP 80/443)
2. **`91XX` range** for Silvasonic service APIs (Controller 9100, Processor 9200)
3. **`9500`** unified internal health port for services without their own API
4. All host-exposed ports configurable via `.env`

## Health Port Convention

- Services **with an API** (Controller, Web-Interface): Health is a route on the API port (`/healthy` on `9100`)
- Services **without an API** (Recorder, BirdNET, BatDetect, Uploader, Weather): Use `silvasonic.core.health` on default port `9500`
- Compose health checks run **inside** the container — no host port needed
- Multiple recorder instances can all use `9500` internally (container isolation)

## Production vs. Development

- **Production**: Only Caddy exposes ports (80/443). All other services communicate via the internal `silvasonic-net` Podman network.
- **Development**: Controller exposed on localhost:9100 for debugging. Recorder has no host port.
