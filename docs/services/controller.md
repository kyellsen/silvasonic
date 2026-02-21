# Controller Service

> **Status:** Implemented (v0.1.0, Scaffold) · **Tier:** 1 · **Instances:** Single · **Port:** 9100

Central orchestration service — detects USB microphones, manages the device inventory, and dynamically manages Tier 2 container lifecycles (start / stop / reconcile) via the Podman REST API (`podman-py`). Follows the **State Reconciliation Pattern** — a pure Listener + Actor with no HTTP API beyond `/healthy`.

---

## 1. The Problem / The Gap

*   **Dynamic Hardware:** A static `compose.yml` cannot handle USB microphones being plugged/unplugged. Each physical microphone must be bound to a dedicated Recorder instance with the appropriate Microphone Profile.
*   **Self-Healing:** If a Recorder crashes, something must detect it and restart it intelligently — verifying the microphone is still present and the device is still enrolled before restarting.
*   **Orchestration:** Users need to toggle services (e.g., "Enable BirdNET", "Disable Weather") via the Web-Interface without SSH access. The Controller bridges this gap via the State Reconciliation Pattern.

## 2. User Benefit

*   **Plug-and-Play:** Automatically detects connected microphones and spins up the appropriate Recorder containers with the correct configuration (Profile Injection).
*   **Resilience:** Automatically repairs broken services via the reconciliation loop (~30s).
*   **Control:** Allows enabling/disabling features via the Web-Interface to save power, CPU, or storage — all routed through DB desired state, never direct commands.

## 3. Core Responsibilities

### Inputs

*   **Podman Socket:** Reads current container state via `podman-py` (`/var/run/container.sock`). Queries containers by `io.silvasonic.owner=controller` labels.
*   **Database (Desired State):** Reads `devices`, `microphone_profiles`, and `system_services` tables to determine what should be running.
*   **Redis (Nudge):** Subscribes to `silvasonic:nudge` for immediate wake-up signals from the Web-Interface.
*   **Hardware Detection:** Polls USB devices to detect microphone connect/disconnect events.

### Processing

*   **Reconciliation Loop (~30s):** Compares desired state (DB) vs. actual state (running containers). Starts missing containers, stops unwanted ones, adopts orphans.
*   **Profile Injection:** Injects Microphone Profile configuration into Recorder containers via environment variables at creation time (ADR-0013).
*   **Device State Evaluation:** Only starts Recorders for devices where `status=online AND enabled=true AND enrollment_status=enrolled AND profile_slug IS NOT NULL`.
*   **Resource Limit Enforcement:** Applies mandatory `mem_limit`, `cpu_limit`, and `oom_score_adj` to every Tier 2 container (ADR-0020).

### Outputs

*   **Container Lifecycle Actions:** Start/stop/restart Tier 2 containers via `podman-py`.
*   **Redis Heartbeats:** Own heartbeat + status aggregation for Tier 2 containers that haven't established their own Redis connection yet.
*   **Database Updates:** Updates `devices` table (device discovery, status changes).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                      |
| ---------------- | --------------------------------------------------------------------------------- |
| **Immutable**    | No — long-running stateful event loop                                             |
| **DB Access**    | Yes — reads `devices`, `microphone_profiles`, `system_services`; writes `devices` |
| **Concurrency**  | Async event loop (`asyncio`) — single-threaded, non-blocking                      |
| **State**        | Stateful (runtime container tracking), but recoverable via reconciliation         |
| **Privileges**   | Privileged (`privileged: true`) — requires Podman socket + hardware access        |
| **Resources**    | Low CPU, Low Memory — must never crash                                            |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure                               |

> [!IMPORTANT]
> The Controller runs as **root inside the container** (no `USER` directive). Podman rootless maps container-root to an unprivileged host user automatically (ADR-0004, ADR-0007). The `privileged: true` flag is required for Podman socket access and USB device detection.

## 5. Configuration & Environment

| Variable / Mount             | Description                               | Default / Example                                                 |
| ---------------------------- | ----------------------------------------- | ----------------------------------------------------------------- |
| `SILVASONIC_CONTROLLER_PORT` | Health endpoint port                      | `9100`                                                            |
| `CONTAINER_SOCKET`           | Podman socket path inside container       | `/var/run/container.sock`                                         |
| `SILVASONIC_NETWORK`         | Podman network name for Tier 2 containers | `silvasonic-net`                                                  |
| `POSTGRES_HOST`              | Database hostname                         | `database`                                                        |
| Socket mount                 | Host Podman socket bind mount             | `${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z`           |
| Workspace mount              | Controller workspace                      | `${SILVASONIC_WORKSPACE_PATH}/controller:/app/workspace:z`        |
| Recorder workspace mount     | Recorder workspace (for provisioning)     | `${SILVASONIC_WORKSPACE_PATH}/recorder:/app/recorder-workspace:z` |

## 6. Technology Stack

*   **Container Management:** `podman-py` (Podman REST API client)
*   **Hardware Detection:** `psutil` / USB device polling
*   **Database:** `sqlalchemy` (2.0+ async), `asyncpg`
*   **Redis:** `redis-py` (async, for heartbeats + nudge subscription)
*   **Config:** `pydantic` (Tier2ServiceSpec model, Microphone Profiles)

## 7. Open Questions & Future Ideas

*   `udev` event-driven USB detection vs. current polling approach — latency vs. complexity trade-off
*   Status aggregator for Tier 2 containers during startup — proxy heartbeats until services report independently
*   Quadlet generation from Tier2ServiceSpec for production deployments (v1.0.0)

## 8. Out of Scope

*   **Does NOT** process audio data (Recorder + Processor's job).
*   **Does NOT** serve the User Interface (Web-Interface's job).
*   **Does NOT** store business data persistently (Database's job).
*   **Does NOT** perform heavy inference (BirdNET / BatDetect's job).
*   **Does NOT** expose an HTTP API beyond `/healthy` — CRUD operations are handled by the Web-Interface.

## 9. References

*   [Controller README](../../services/controller/README.md) — full implementation spec (state machine, reconciliation, shutdown semantics, QoS tables)
*   [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md) — step-by-step implementation plan
*   [ADR-0013](../adr/0013-tier2-container-management.md) — Tier 2 Container Management
*   [ADR-0016](../adr/0016-hybrid-yaml-db-profiles.md) — Hybrid YAML/DB Profile Management
*   [ADR-0017](../adr/0017-service-state-management.md) — Service State Management
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — SilvaService lifecycle
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — Resource Limits & QoS
*   [Messaging Patterns](../arch/messaging_patterns.md) — State Reconciliation Pattern, Nudge
*   [Port Allocation](../arch/port_allocation.md) — Controller on port 9100
*   [Microphone Profiles](../arch/microphone_profiles.md) — Profile seed files
*   [Glossary](../glossary.md) — canonical definition
*   [VISION.md](../../VISION.md) — services architecture
