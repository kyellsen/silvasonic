# Tier 2 Container Management — Implementation Roadmap

> **Target:** v0.3.0 — Controller manages Recorder lifecycle (start/stop)
>
> **References:** [ADR-0013](docs/adr/0013-tier2-container-management.md), [ADR-0007 §6](docs/adr/0007-rootless-os-compliance.md), [ADR-0009](docs/adr/0009-zero-trust-data-sharing.md), [VISION.md](VISION.md)

---

## Phase 1: Controller ↔ Podman Socket Connection

**Goal:** Controller connects to the host Podman engine and can list running containers.

### Tasks

- [ ] Add `podman-py` as dependency to `services/controller/pyproject.toml`
- [ ] Create `silvasonic/controller/podman_client.py` — PodmanClient wrapper
  - Connect to socket (`CONTAINER_SOCKET` env var, default `/var/run/container.sock`)
  - `ping()` health check on startup
  - Reconnect logic (socket may not be available immediately)
- [ ] Verify socket mount works in `compose.yml` (`${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z`)
- [ ] Unit test: mock PodmanClient, verify connection logic
- [ ] Integration test: Controller container connects to host Podman, lists containers

### Config Changes (✅ Already Applied)

| File                    | Change                                                                    |
| ----------------------- | ------------------------------------------------------------------------- |
| `compose.yml`           | Socket volume mount, `CONTAINER_SOCKET` and `SILVASONIC_NETWORK` env vars |
| `.env` / `.env.example` | `SILVASONIC_PODMAN_SOCKET`, `SILVASONIC_NETWORK` activated                |

---

## Phase 2: Container Lifecycle Management

**Goal:** Controller can start, stop, list, and reconcile Tier 2 containers.

### Tasks

- [ ] Create Pydantic model `Tier2ServiceSpec` defining:
  - Image name, container name pattern
  - Labels (auto-populated: `io.silvasonic.tier`, `.owner`, `.service`, `.device_id`, `.profile`)
  - Environment variables, devices, mounts (with RO/RW distinction per ADR-0009)
  - Restart policy (`on-failure`, max 5 retries)
  - Network name (from `SILVASONIC_NETWORK`)
- [ ] Create `silvasonic/controller/container_manager.py`:
  - `start(spec: Tier2ServiceSpec) → Container` — calls `podman.containers.run()`
  - `stop(name: str)` — sends SIGTERM, waits for graceful shutdown
  - `list_managed() → list[Container]` — queries `io.silvasonic.owner=controller`
  - `reconcile()` — compares desired state vs. actual, adopts or cleans up
- [ ] Implement reconciliation loop (async, ~30s interval)
- [ ] Unit tests: mock `podman-py`, verify start/stop/reconcile logic
- [ ] Integration test: start a test container, verify labels, stop it

### Key Design Decisions

| Decision                                                        | Rationale                                                                      |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `restart_policy={"Name": "on-failure", "MaximumRetryCount": 5}` | Podman handles immediate restarts; Controller reconciliation is the safety net |
| No host port exposure                                           | Controller reaches Tier 2 via container-internal IP + port                     |
| Deliberate stop → stop Tier 2                                   | `SIGTERM` to Controller triggers graceful Tier 2 shutdown                      |
| Controller crash → Tier 2 keeps running                         | Data Capture Integrity is paramount                                            |

---

## Phase 3: Recorder Spawning with Profile Injection

**Goal:** Controller detects USB microphones and starts Recorder containers dynamically.

### Tasks

- [ ] Replace `SIMULATE_RECORDER_SPAWN` placeholder in `controller/__main__.py`
- [ ] Create `Tier2ServiceSpec` for Recorder:
  - Image: `silvasonic-recorder:latest`
  - Name pattern: `silvasonic-recorder-<device_id>`
  - Devices: `/dev/snd:/dev/snd`
  - Group add: `audio`
  - Privileged: `true` (see ADR-0007 §6)
  - Mounts: Recorder workspace = RW (producer)
  - Env vars: `RECORDER_DEVICE`, `RECORDER_PROFILE` (Profile Injection)
- [ ] Implement basic USB microphone detection (or hardcoded device for MVP)
- [ ] Connect `monitor_recorder_spawn()` to actual container health checks via `podman-py`
- [ ] Implement Recorder health monitoring loop (check container status + health endpoint)
- [ ] Add Redis heartbeat to Recorder (fire-and-forget via `SilvaService`, ADR-0019)
- [ ] Integration test: Controller spawns Recorder container, verifies health, stops it

---

## Phase 4: Integration & Hardening

**Goal:** End-to-end lifecycle works reliably. System survives crashes and restarts.

### Tasks

- [ ] Implement graceful shutdown handler in Controller (`main()`)
  - On SIGTERM: stop all owned Tier 2 containers, then exit
- [ ] Test crash recovery: kill Controller, verify Recorder keeps running
- [ ] Test reconciliation: restart Controller, verify it adopts existing Recorder
- [ ] Test multi-instance: start 2 Recorders for different devices, verify labels
- [ ] Implement log access via `podman-py` (`container.logs()`)
- [ ] Update smoke tests to verify Controller ↔ Recorder lifecycle
- [ ] Update `VISION.md` roadmap: mark v0.3.0 as 🔨 In Progress

---

## Out of Scope (Deferred)

| Item                                            | Target Version              |
| ----------------------------------------------- | --------------------------- |
| Actual audio recording (`recorder/__main__.py`) | v0.4.0                      |
| USB HotPlug detection                           | v0.4.0                      |
| Resource limits (CPU/RAM)                       | Future (not needed for MVP) |
| Uploader, BirdNET, BatDetect as Tier 2          | v0.6.0+                     |
| Icecast live Opus stream (Recorder → Icecast)   | v0.9.0                      |
| Quadlet generation for production               | v1.0.0                      |
