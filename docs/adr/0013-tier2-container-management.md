# ADR-0013: Tier 2 Container Management — Podman-Only with podman-py

> **Status:** Accepted • **Date:** 2026-02-17

## 1. Context & Problem

The Controller (Tier 1) must dynamically manage **Tier 2 services** (Recorder, Uploader, BirdNET, BatDetect, Weather) at runtime — starting, stopping, and configuring them based on hardware detection and scheduling. Key constraints:

*   **Immutable Tier 2 containers:** Configuration is injected via environment variables at launch time (Profile Injection). Only the Recorder has no database access; other Tier 2 services (Uploader, BirdNET, etc.) may access the database.
*   **Multi-instance support:** Multiple Recorder instances may run concurrently (one per USB microphone, HotPlug). One Uploader per Cloud Storage Account.
*   **Pre-built images:** All images are built before deployment (`just build`). The Controller never builds images at runtime.
*   **Container-in-Container (DooD):** The Controller itself runs in a container and manages sibling containers on the host engine via the host's Podman socket (Docker-out-of-Docker pattern).
*   **Years of autonomous operation:** Minimal moving parts, deterministic behavior, no runtime dependencies on Compose semantics.

## 2. Decision

**We chose:** Podman-only with `podman-py` (native Podman REST API client) for Tier 2 container management.

**Reasoning:**

*   **Single Engine, Single API:** Silvasonic is an embedded edge device (Raspberry Pi 5) where the operating system is provisioned by us (Ansible). Docker support provides zero production value while adding complexity. By committing to Podman-only, we pin exactly one engine and one API surface.
*   **Native REST API (libpod):** `podman-py` communicates directly with the Podman socket via HTTP — no CLI binary needed inside the Controller container, no subprocess overhead, no CLI output parsing, no version skew between CLI and host engine.
*   **No Compose at Runtime:** The Controller speaks directly to the Podman API for `containers.run()`, `containers.list()`, `containers.stop()`, etc. This avoids the well-documented incompatibilities between `podman-compose` and Docker Compose V2 semantics. Compose remains for Tier 1 (static infrastructure) only.
*   **systemd Integration:** Podman's tight integration with systemd (socket activation, Quadlet) ensures Tier 2 containers survive Controller restarts, and the Controller can reconcile desired vs. actual state on startup.

> [!NOTE]
> This ADR governs the **Controller's runtime Tier 2 management** only. The static `compose.yml` for Tier 1 services is managed via `podman-compose` (see ADR-0004).

### 2.1. Architecture

```
Controller (podman-py → Podman REST API)
    │
    ├─ Standard launch: podman.containers.run("silvasonic-recorder:latest", ...)
    │   └─ Config from Tier 2 service spec (env vars, devices, mounts)
    │
    └─ Multi-instance: podman.containers.run(..., name="silvasonic-recorder-<device>")
        └─ Dynamic name, per-device env vars, same network
    │
    ▼
Host Podman Socket (/var/run/container.sock — mounted into Controller)
    │
    ▼
Podman Engine → Tier 2 Containers (sibling containers on host)
```

### 2.2. Ownership & Reconciliation via Labels

Every Tier 2 container is tagged with OCI labels for lifecycle management: `io.silvasonic.tier`, `io.silvasonic.owner`, `io.silvasonic.service`, `io.silvasonic.device_id`, `io.silvasonic.profile`. On startup, the Controller reconciles desired vs. actual state by querying containers with `io.silvasonic.owner=controller`.

### 2.3. Network Strategy

Tier 2 containers join the **same custom network** as Tier 1 services (`SILVASONIC_NETWORK` env var). This enables health endpoint access, database/Redis connectivity, and unified heartbeat publishing (see [ADR-0019](0019-unified-service-infrastructure.md)). Pods were rejected — Podman Pods share a network namespace, making independent lifecycle management impossible.

### 2.4. Restart Policy & Crash Recovery

*   **Podman handles immediate crash recovery** — restart policy `on-failure` (max 5 retries) is set on every `containers.run()` call.
*   **The Controller runs a periodic reconciliation loop** (~30s) as a safety net — detecting orphaned, stuck, or missing containers and correcting the state.
*   **Controller crash or restart:** Tier 2 containers **keep running** independently. On restart, the Controller reconciles via label query, adopts existing containers without restarting them.
*   **Priority:** Data Capture Integrity > Clean Shutdown. A Recorder must never be interrupted by a Controller restart.

### 2.5. Resource Limits & QoS

Every `containers.run()` call **MUST** include resource limit parameters (`memory_limit`, `cpu_quota`, `oom_score_adj`). See [ADR-0020](0020-resource-limits-qos.md) for the full resource budget and OOM priority hierarchy.

### 2.6. Logging

Tier 2 container logs are accessed via `podman-py` (`container.logs()`), **not** via the filesystem. Tier 2 containers write to stdout/stderr; Podman captures these logs natively.

## 3. Options Considered

*   **`python-on-whales` (CLI-Wrapper, engine-agnostic):** Rejected. Wraps CLI via subprocess — requires CLI binary inside the Controller container. Engine abstraction provides no benefit for a single-engine edge device.
*   **`docker-py` + Podman Docker-compat socket:** Rejected. Podman's Docker-compatible API has known subtle differences for device mapping, `privileged`, and `group_add`.
*   **Dual-SDK (`podman-py` + `docker-py`):** Rejected. Disproportionate complexity for zero benefit.
*   **Raw `subprocess` calls:** Rejected. No type safety, fragile string parsing, poor error handling.

## 4. Consequences

*   **Positive:**
    *   Single engine, single API — deterministic behavior for years of autonomous operation.
    *   No CLI binary needed inside the Controller container.
    *   Direct HTTP communication via socket — no subprocess overhead.
    *   Label-based ownership enables clean reconciliation and garbage collection without Compose.
*   **Negative:**
    *   Contributors must have Podman installed to test the Controller locally.
    *   `podman-py` becomes a runtime dependency of the Controller service.
    *   The host Podman socket must be mounted into the Controller container.
    *   Podman socket activation (`podman.socket` systemd unit) must be enabled on the host.

## 5. Configuration

| File | Config | Value |
| --- | --- | --- |
| `compose.yml` | Socket mount | `${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z` |
| `compose.yml` | Network env | `SILVASONIC_NETWORK=silvasonic-net` |
| `.env` | Podman socket | `SILVASONIC_PODMAN_SOCKET=/run/user/1000/podman/podman.sock` |
| `.env` | Network name | `SILVASONIC_NETWORK=silvasonic-net` |
