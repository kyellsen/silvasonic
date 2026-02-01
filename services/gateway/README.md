# Container: Gateway

> **Service Name:** `gateway`
> **Container Name:** `silvasonic-gateway`
> **Package Name:** `silvasonic-gateway` (Caddy w/ Config)

## 1. The Problem / The Gap
*   **Single Entry Point:** The system runs multiple web services (UI, API, MinIO? etc.). Users shouldn't need to remember port 8000, 8080, 3000.
*   **Security:** Needs a central point for TLS (future) and Basic Auth (if configured).

## 2. User Benefit
*   **Ease of Use:** Access the whole system via `http://silvasonic.local`.
*   **Performance:** Caddy handles static asset compression and caching efficiently.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **HTTP Requests**: From User Browser.
*   **Processing**:
    *   **Reverse Proxying**: Routing based on path (`/api` -> Controller/API, `/` -> Web Interface).
    *   **Load Balancing**: (If multiple replicas exist, rare).
*   **Outputs**:
    *   **HTTP Responses**.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **High**. Async IO.
*   **State**: **Stateless**.
*   **Privileges**: **Rootless**. Binds to port 8080/8443 internally, mapped to 80/443 on host via Podman (or high ports if rootless on host).
*   **Resources**: Low.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `DOMAIN_NAME`: Hostname.
*   **Volumes**:
    *   `./Caddyfile` -> `/etc/caddy/Caddyfile`.
    *   `${SILVASONIC_WORKSPACE_PATH}/gateway/logs` -> `/var/log/caddy`.
    *   `caddy_data` -> For certificates.
*   **Dependencies**:
    *   `web-interface` (Upstream).
    *   `controller` (Upstream API).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** run application logic.
*   **Does NOT** generate HTML (Web Interface job).
*   **Does NOT** store data (Database job).
*   **Does NOT** manage hardware (Controller job).
*   **Does NOT** handle internal message brokering (Redis job).

## 7. Technology Stack
*   **Base Image**: `caddy:2-alpine`.
*   **Key Libraries**:
    *   Caddy Web Server.
*   **Build System**: Use `services/gateway/Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Caddy is modern, automatic HTTPS capable (even locally), and simple config.
*   **Alternatives**: Nginx (Config too verbose for this use case), Traefik (Overkill/Too complex for a single appliance).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
