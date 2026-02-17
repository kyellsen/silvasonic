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
*   **Complexity Reduction:** Removing Docker as a runtime target eliminates engine-detection logic, binary-selection ternaries, and dual code paths throughout the codebase (see Section 6).

> [!NOTE]
> This ADR governs the **Controller's runtime Tier 2 management** only. The static `compose.yml` for Tier 1 services is managed via `podman-compose` (see ADR-0004).

**Architecture:**

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

**Ownership & Reconciliation via Labels:**

Every Tier 2 container is tagged with labels for lifecycle management:

```python
labels = {
    "io.silvasonic.tier": "2",
    "io.silvasonic.owner": "controller",
    "io.silvasonic.service": "recorder",
    "io.silvasonic.device_id": device_id,
    "io.silvasonic.profile": profile_name,
}
```

On startup, the Controller reconciles desired vs. actual state by querying containers with `io.silvasonic.owner=controller`.

## 3. Options Considered

*   **`python-on-whales` (CLI-Wrapper, engine-agnostic):** Rejected. While offering explicit Podman + Docker support via `client_call`, it wraps the CLI via subprocess — requiring the CLI binary installed inside the Controller container. Its Compose integration relies on Docker Compose V2 semantics, which are not guaranteed to work identically with `podman-compose`. For a single-engine edge device, the added complexity of engine abstraction provides no benefit.
*   **`docker-py` + Podman Docker-compat socket:** Rejected. Podman's Docker-compatible API is "best effort" — critical features for Silvasonic (device mapping, `privileged`, `group_add`) have known subtle differences. No Compose support.
*   **Dual-SDK (`podman-py` + `docker-py`):** Rejected. Requires two SDKs, two APIs, and a custom abstraction layer. Disproportionate complexity.
*   **Raw `subprocess` calls:** Rejected. No type safety, fragile string parsing, poor error handling.

## 4. Consequences

*   **Positive:**
    *   Single engine, single API — deterministic behavior for years of autonomous operation.
    *   No CLI binary needed inside the Controller container — smaller image, no version skew.
    *   Direct HTTP communication via socket — no subprocess overhead.
    *   `SILVASONIC_CONTAINER_ENGINE` variable removed — complexity reduction across scripts.
    *   Label-based ownership enables clean reconciliation and garbage collection without Compose.
    *   Compose profiles in `compose.yml` remain as documentation/templates for Tier 2 service configuration.
*   **Negative:**
    *   Contributors must have Podman installed to test the Controller's Tier 2 management logic locally.
    *   `podman-py` becomes a runtime dependency of the Controller service.
    *   The host Podman socket must be mounted into the Controller container (elevated privileges, mitigated by existing `privileged: true`).
    *   Podman socket activation (`podman.socket` systemd unit) must be enabled on the host.

## 5. Implementation Notes

### Controller `compose.yml` Changes

```yaml
controller:
    volumes:
      # Existing volumes...
      - ${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z
    environment:
      CONTAINER_SOCKET: /var/run/container.sock
```

### `.env` Additions

```bash
# Podman socket (mounted into Controller for Tier 2 management)
# Rootless (default) — adjust UID if necessary:
SILVASONIC_PODMAN_SOCKET=/run/user/1000/podman/podman.sock
```

### Python Usage Pattern

```python
from podman import PodmanClient

# Connect to host Podman via mounted socket
podman = PodmanClient(base_url="unix:///var/run/container.sock")

# Standard single-instance launch
container = podman.containers.run(
    image="silvasonic-recorder:latest",
    name="silvasonic-recorder-mic1",
    detach=True,
    environment={"RECORDER_DEVICE": "hw:1,0", "RECORDER_PROFILE": "48kHz-stereo"},
    devices=["/dev/snd:/dev/snd"],
    mounts=[{"type": "bind", "source": "/mnt/data/workspace/recorder", "target": "/app/workspace"}],
    labels={
        "io.silvasonic.tier": "2",
        "io.silvasonic.owner": "controller",
        "io.silvasonic.service": "recorder",
        "io.silvasonic.device_id": "mic1",
    },
    privileged=True,
)

# Reconcile on startup — query all owned containers
managed = podman.containers.list(
    filters={"label": ["io.silvasonic.owner=controller"]}
)
```

## 6. Codebase Simplification (Podman-Only) — ✅ Completed

All engine-detection logic has been removed. The following changes were applied:

| File                    | Change                                                                  | Status |
| ----------------------- | ----------------------------------------------------------------------- | ------ |
| `scripts/compose.py`    | Removed `get_container_engine()`, hardcoded `podman-compose`            | ✅      |
| `scripts/build.py`      | Removed `get_container_engine()`, uses `"podman"` directly              | ✅      |
| `scripts/prune.py`      | Removed engine ternary, uses `"podman"` directly                        | ✅      |
| `scripts/nuke.py`       | Removed engine detection, uses `"podman"` directly                      | ✅      |
| `scripts/init.py`       | Simplified `check_container_engine()` to check for `podman` only        | ✅      |
| `.env` / `.env.example` | Removed `SILVASONIC_CONTAINER_ENGINE`, added `SILVASONIC_PODMAN_SOCKET` | ✅      |
| `justfile`              | Updated comment "Podman / Docker" → "Podman"                            | ✅      |
| `compose.yml`           | Updated header comment                                                  | ✅      |
| ADR-0004                | Removed Docker-compat references                                        | ✅      |
| ADR-0007                | Simplified — Docker references removed                                  | ✅      |
