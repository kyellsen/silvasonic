# Port Allocation

> **Status:** Normative (Mandatory) · **Implemented:** Partial (since v0.1.0) — Database (5432), Controller (9100), Recorder health (9500) are AS-IS; all others TO-BE
> **Scope:** System-wide port scheme

All Silvasonic services use a consistent port scheme. Ports are configured via `.env`.

## Port Table

| Service                | Internal Port | Host Port (Dev) | `.env` Variable                 | Status             |
| ---------------------- | ------------- | --------------- | ------------------------------- | ------------------ |
| **TimescaleDB**        | 5432          | 5432            | `SILVASONIC_DB_PORT`            | ✅ Implemented      |
| **Redis**              | 6379          | 6379            | `SILVASONIC_REDIS_PORT`         | ✅ Implemented v0.2 |
| **Controller**         | 9100          | 9100            | `SILVASONIC_CONTROLLER_PORT`    | ✅ Implemented      |
| **Web-Mock** (Dev UI)  | 8001          | 8001            | `SILVASONIC_WEB_MOCK_PORT`      | ✅ Implemented v0.2 |
| **Web-Interface**      | 8000          | 8000            | `SILVASONIC_WEBUI_PORT`         | 📋 Planned v0.8     |
| **Processor**          | 9200          | —               | `SILVASONIC_PROCESSOR_PORT`     | 📋 Planned v0.5     |
| **Recorder** (Health)  | 9500          | —               | — (internal only)               | ✅ Scaffold         |
| **BirdNET** (Health)   | 9500          | —               | — (internal only)               | 📋 Planned v1.1     |
| **BatDetect** (Health) | 9500          | —               | — (internal only)               | 📋 Planned v1.3     |
| **Uploader** (Health)  | 9500          | —               | — (internal only)               | 📋 Planned v0.6     |
| **Weather** (Health)   | 9500          | —               | — (internal only)               | 📋 Planned v1.2     |
| Gateway (Caddy) HTTP   | 80            | 80              | `SILVASONIC_GATEWAY_HTTP_PORT`  | 📋 Planned v0.7     |
| Gateway (Caddy) HTTPS  | 443           | 443             | `SILVASONIC_GATEWAY_HTTPS_PORT` | 📋 Planned v0.7     |
| **Icecast**            | 8080          | 8080            | `SILVASONIC_ICECAST_PORT`       | 📋 Planned v0.9     |

> **Note:** Tailscale creates a VPN overlay — no dedicated ports needed.

## Principles

1. **Standard ports** for well-known services (PostgreSQL 5432, Redis 6379, HTTP 80/443)
2. **`80XX` range** for web-facing UIs (Web-Interface 8000, Web-Mock 8001, Icecast 8080)
3. **`91XX` range** for Silvasonic service APIs (Controller 9100, Processor 9200)
4. **`9500`** unified internal health port for services without their own API
5. All host-exposed ports configurable via `.env`
6. **No internal port collisions** — each service uses a unique internal port to avoid confusion

## Health Port Convention

- Services **with an API** (Controller, Web-Interface): Health is a route on the API port (`/healthy` on `9100`)
- Services **without an API** (Recorder, BirdNET, BatDetect, Uploader, Weather): Use `silvasonic.core.health` on default port `9500`
- Compose health checks run **inside** the container — no host port needed
- Multiple recorder instances can all use `9500` internally (container isolation)

## Production vs. Development

- **Production**: Only Caddy exposes ports (80/443). All other services communicate via the internal `silvasonic-net` Podman network.
- **Development**: Controller (9100), Web-Mock (8001), Database (5432), Redis (6379) exposed on localhost for debugging. Recorder has no host port.
