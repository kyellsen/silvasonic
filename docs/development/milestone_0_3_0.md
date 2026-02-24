# Milestone v0.3.0 — Tier 2 Container Management

> **Target:** v0.3.0 — Controller manages Recorder lifecycle (start/stop)
>
> **References:** [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0007 §6](../adr/0007-rootless-os-compliance.md), [ADR-0009](../adr/0009-zero-trust-data-sharing.md), [VISION.md](../../VISION.md)

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
  - Resource limits: `memory_limit`, `cpu_limit`, `oom_score_adj` (ADR-0020)
- [ ] Create `silvasonic/controller/container_manager.py`:
  - `start(spec: Tier2ServiceSpec) → Container` — calls `podman.containers.run()` with resource limits
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

## Phase 3: USB Detection, HotPlug & Recorder Spawning

**Goal:** Controller detects USB microphones in near-realtime (≤ 1 s), matches profiles, and starts Recorder containers dynamically.

### Tasks — USB Detection & HotPlug

- [ ] Add `pyudev` as dependency to `services/controller/pyproject.toml`
- [ ] Create `silvasonic/controller/device_scanner.py` — `DeviceScanner`
  - Enumerate ALSA cards via `/proc/asound/cards`
  - Correlate each card with USB parent via `pyudev` / `sysfs` (→ `DeviceInfo`)
  - Extract: `usb_vendor_id`, `usb_product_id`, `usb_serial`, `alsa_name`, `alsa_device`
- [ ] Create `silvasonic/controller/hotplug_monitor.py` — `HotPlugMonitor`
  - `pyudev.Monitor` (subsystem `sound`) as dedicated `asyncio.Task`
  - On `add`: scan single device, write to DB, trigger reconciliation
  - On `remove`: set `status=offline`, trigger reconciliation
  - **Latency target: ≤ 1 second** from USB plug to reconciliation trigger
  - Graceful degradation: if `/run/udev` unavailable → fallback to polling with log warning
- [ ] Implement stable device identity:
  - With USB serial: `{vendor_id}-{product_id}-{serial}` (globally unique)
  - Without serial: `{vendor_id}-{product_id}-port{bus_path}` (port-bound)
  - Store as `devices.name` (PK) → determines Recorder name + workspace path

### Tasks — Profile Matching & Auto-Enrollment

- [ ] Create `silvasonic/controller/profile_matcher.py` — `ProfileMatcher`
  - Score 100: USB Vendor+Product ID match → auto-enroll
  - Score 50: ALSA name substring match → suggest in Web-Interface
  - Score 0: no match → `pending`
- [ ] Add `auto_enrollment` to `SystemSettings` Pydantic schema and `config/defaults.yml` (default: `true`)
- [ ] Read `auto_enrollment` from `system_config` on each reconciliation cycle (runtime-changeable)

### Tasks — Recorder Spawning

- [ ] Replace `SIMULATE_RECORDER_SPAWN` placeholder in `controller/__main__.py`
- [ ] Create `Tier2ServiceSpec` for Recorder:
  - Image: `silvasonic-recorder:latest`
  - Name pattern: `silvasonic-recorder-{device_id}`
  - Devices: `/dev/snd:/dev/snd`
  - Group add: `audio`
  - Privileged: `true` (see ADR-0007 §6)
  - Mounts: Recorder workspace = RW (producer)
  - Env vars: `RECORDER_DEVICE`, `RECORDER_PROFILE` (Profile Injection)
- [ ] Connect `monitor_recorder_spawn()` to actual container health checks via `podman-py`
- [ ] Implement Recorder health monitoring loop (check container status + health endpoint)
- [ ] Add Redis heartbeat to Recorder (fire-and-forget via `SilvaService`, ADR-0019)
- [ ] Integration test: Controller spawns Recorder container, verifies health, stops it
- [ ] Integration test: HotPlug — plug USB device, verify Recorder starts within 1 s

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
- [ ] Update `ROADMAP.md`: mark v0.3.0 as 🔨 In Progress

---

## Out of Scope (Deferred)

| Item                                            | Target Version |
| ----------------------------------------------- | -------------- |
| Actual audio recording (`recorder/__main__.py`) | v0.4.0         |
| Uploader, BirdNET, BatDetect as Tier 2          | v0.6.0+        |
| Icecast live Opus stream (Recorder → Icecast)   | v0.9.0         |
| Quadlet generation for production               | v1.0.0         |

> **Note:** Resource limits (CPU/RAM) and QoS (`oom_score_adj`) are now **in scope** for Phase 2 as part of the `Tier2ServiceSpec` model. See [ADR-0020](../adr/0020-resource-limits-qos.md).
>
> **Note:** USB HotPlug detection (≤ 1 s latency via `pyudev.Monitor`) is now **in scope** for Phase 3. Previously deferred to v0.4.0.
