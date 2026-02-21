# Gateway Service

> **Status:** Planned (v0.7.0) · **Tier:** 1 · **Instances:** Single · **Ports:** 80 (HTTP), 443 (HTTPS)

Caddy-based reverse proxy providing a unified entry point, HTTPS termination, internal routing, and authentication for all Silvasonic web services.

---

## 1. The Problem / The Gap

*   **Single Entry Point:** The system runs multiple web services (Web-Interface, Icecast). Users should not need to remember individual ports — everything must be accessible via one hostname.
*   **Security:** A central point for TLS termination and authentication (Basic Auth or mutual TLS) is required, especially for field-deployed devices accessible over Tailscale.

## 2. User Benefit

*   **Ease of Use:** Access the entire system via `https://silvasonic.local` — the Gateway routes requests transparently to the correct backend.
*   **Performance:** Caddy handles static asset compression (gzip/brotli) and caching efficiently.
*   **Security:** Automatic HTTPS (via Caddy's built-in ACME support) without manual certificate management.

## 3. Core Responsibilities

### Inputs

*   **HTTP/HTTPS Requests:** From user browsers, external API clients, and Tailscale-tunneled connections.

### Processing

*   **Reverse Proxying:** Path-based routing to internal services (e.g., `/` → Web-Interface, `/stream` → Icecast).
*   **TLS Termination:** Handles HTTPS; backends communicate over plain HTTP on the internal network.
*   **Authentication:** Enforces Basic Auth or other configured authentication methods.
*   **Compression & Caching:** Automatic gzip/brotli for static assets.

### Outputs

*   **HTTP/HTTPS Responses:** Proxied responses from internal services.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                           |
| ---------------- | ---------------------------------------------------------------------- |
| **Immutable**    | No — long-running server, but config-driven (Caddyfile reload)         |
| **DB Access**    | No                                                                     |
| **Concurrency**  | High — async I/O, handles many concurrent connections                  |
| **State**        | Stateless (request routing) + TLS certificate state (`caddy_data`)     |
| **Privileges**   | Rootless (binds to 80/443 inside container; Podman maps to host ports) |
| **Resources**    | Low — minimal CPU and memory footprint                                 |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure                    |

> [!NOTE]
> In production, the Gateway is the **only** service exposing ports to the host (80/443). All other services communicate exclusively via the internal `silvasonic-net` Podman network.

## 5. Configuration & Environment

| Variable / Mount                | Description                        | Default / Example                                            |
| ------------------------------- | ---------------------------------- | ------------------------------------------------------------ |
| `SILVASONIC_GATEWAY_HTTP_PORT`  | Host-exposed HTTP port             | `80`                                                         |
| `SILVASONIC_GATEWAY_HTTPS_PORT` | Host-exposed HTTPS port            | `443`                                                        |
| `SILVASONIC_DOMAIN_NAME`        | Hostname for the station           | `silvasonic.local`                                           |
| Caddyfile mount                 | Caddy configuration (read-only)    | `./services/gateway/Caddyfile:/etc/caddy/Caddyfile:ro,z`     |
| Data mount                      | TLS certificates (ACME), persisted | `${SILVASONIC_WORKSPACE_PATH}/gateway/data:/data:z`          |
| Config mount                    | Caddy runtime config state         | `${SILVASONIC_WORKSPACE_PATH}/gateway/config:/config:z`      |
| Log mount                       | Caddy access/error logs            | `${SILVASONIC_WORKSPACE_PATH}/gateway/logs:/var/log/caddy:z` |

> [!NOTE]
> Caddy's `/data` (certificates) and `/config` (runtime state) are stored via **bind mounts** into the Gateway workspace — not as Named Volumes. This keeps ADR-0006 intact (Named Volumes only for database). Caddy auto-regenerates certificates if the data directory is empty.

## 6. Technology Stack

*   **Base Image:** `caddy:2-alpine`
*   **Web Server:** Caddy 2 — automatic HTTPS, simple Caddyfile configuration
*   **Build File:** `services/gateway/Containerfile`

> [!NOTE]
> Gateway is **not a Python service** — it has no `pyproject.toml`, no `silvasonic.*` package, and does not use the `SilvaService` base class. It is a pure infrastructure container with a Caddyfile configuration.

## 7. Open Questions & Future Ideas

*   Automatic HTTPS with Let's Encrypt vs. self-signed certificates for `.local` domains
*   Authentication strategy: Basic Auth (simple) vs. OAuth2 proxy (complex but more secure)
*   Rate limiting for external access via Tailscale
*   Alternatives considered and rejected: Nginx (config too verbose for single-appliance use case), Traefik (overkill for a single-node deployment)

## 8. Out of Scope

*   **Does NOT** run application logic (Web-Interface's job).
*   **Does NOT** generate HTML or serve a UI (Web-Interface's job).
*   **Does NOT** store data (Database's job).
*   **Does NOT** manage hardware or containers (Controller's job).
*   **Does NOT** handle internal service messaging (Redis's job).
*   **Does NOT** stream audio (Icecast's job — Gateway only proxies to it).

## 9. References

*   [Port Allocation](../arch/port_allocation.md) — Gateway on ports 80/443
*   [ADR-0003](../adr/0003-frontend-architecture.md) — Frontend Architecture
*   [ADR-0006](../adr/0006-bind-mounts-over-volumes.md) — Bind Mounts vs. Named Volumes (caddy_data exception TBD)
*   [Glossary: Gateway](../glossary.md) — canonical definition
*   [VISION.md](../../VISION.md) — roadmap entry (v0.7.0)
