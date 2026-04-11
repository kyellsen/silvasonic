# silvasonic-gateway

> **Status:** Implemented (since v0.1.0) · **Tier:** 1 (Infrastructure) · **Instances:** Single · **Port:** 80 / 443

**AS-IS:** Unified Entry Point for all web services of the Silvasonic system, powered by Caddy. Routes web traffic and provides basic authentication.
**Target:** Add TLS features and stream proxying to Icecast (v1.1.0).

---

## 1. The Problem / The Gap

*   **Unified Access:** Users should only need to access one port (80/443) instead of jumping between multiple different ports for UI, db-viewer, and API endpoints. 
*   **Security:** Needs basic authentication and SSL/TLS termination to protect data in transit.

## 2. User Benefit

*   Single URL to access the entire system without specifying ports.
*   Secure by default without needing external configuration.
*   Centralizes basic authentication rules.

## 3. Core Responsibilities

### Inputs
*   HTTP/HTTPS Internet traffic from users.

### Processing
*   Reverse proxying rules (`Caddyfile`) based on path prefixes (`/web-mock`, `/db-viewer`, `/docs`).
*   Path stripping and traffic direction to the internal Podman bridge network (`silvasonic-net`).

### Outputs
*   Proxied HTML, CSS, Javascript, and Data payload to clients.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                   |
| ---------------- | -------------------------------------------------------------- |
| **Immutable**    | Yes                                                            |
| **DB Access**    | No                                                             |
| **Concurrency**  | Caddy Event Loop (Go)                                          |
| **State**        | Stateful (Caddy data and certificates are persisted)           |
| **Privileges**   | Rootless (runs internally, maps out to host 80/443)            |
| **Resources**    | Low                                                            |
| **QoS Priority** | `oom_score_adj=0`                                              |

## 5. Configuration & Environment

| Variable / Mount                  | Description                                    | Default / Example    |
| --------------------------------- | ---------------------------------------------- | -------------------- |
| `SILVASONIC_GATEWAY_HTTP_PORT`    | Public HTTP port exposed to the host           | `80`                 |
| `SILVASONIC_GATEWAY_HTTPS_PORT`   | Public HTTPS port exposed to the host          | `443`                |
| `SILVASONIC_DOMAIN_NAME`          | Base routing domain                            | `silvasonic.local`   |
| `/etc/caddy/Caddyfile` (Mount)    | Caddy routing configuration file               | (Mapped from repo)   |
| `caddy_data` (Volume)             | Persistence for Caddy certificates and certs   | (Named volume)       |
| `caddy_config` (Volume)           | Internal Caddy config state                    | (Named volume)       |
| `/var/log/caddy` (Mount)          | Persisted Caddy access logs                    | (Mapped to workspace)|

## 6. Technology Stack

*   **Server:** Caddy 2 (Alpine)

## 7. Out of Scope

*   Serving dynamic data (proxies requests to Tier 1 services).
*   System state orchestration (Controller handles this).

## 8. Implementation Details (Domain Specific)

*   Gateway enforces Basic Authentication using bcrypt-hashed passwords in the `Caddyfile`.
*   Uses `handle_path` internally to strip prefixes like `/web-mock` before forwarding the requests.

## 9. References

*   [VISION.md](../../VISION.md) - Project Architecture
