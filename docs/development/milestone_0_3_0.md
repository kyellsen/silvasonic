# Milestone v0.3.0 — Tier 2 Container Management

> **Target:** v0.3.0 — Controller manages Recorder lifecycle (start/stop), Hardware Detection, State Reconciliation & Log Streaming
>
> **References:** [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0007 §6](../adr/0007-rootless-os-compliance.md), [ADR-0009](../adr/0009-zero-trust-data-sharing.md), [VISION.md](../../VISION.md), [Controller README](../../services/controller/README.md), [Recorder README](../../services/recorder/README.md)

---

## Phase 1: Controller ↔ Podman Socket Connection

**Goal:** Controller connects to the host Podman engine and can list running containers.

### Tasks

- [x] Add `podman-py` as dependency to `services/controller/pyproject.toml`
- [x] Create `silvasonic/controller/podman_client.py` — PodmanClient wrapper
  - Connect to socket (`CONTAINER_SOCKET` env var, default `/var/run/container.sock`)
  - `ping()` health check on startup
  - Reconnect logic (socket may not be available immediately)
- [x] Verify socket mount works in `compose.yml` (`${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z`)
- [x] Unit test: mock PodmanClient, verify connection logic
- [ ] Integration test: Controller container connects to host Podman, lists containers

### Config Changes (✅ Already Applied)

| File                    | Change                                                                    |
| ----------------------- | ------------------------------------------------------------------------- |
| `compose.yml`           | Socket volume mount, `CONTAINER_SOCKET` and `SILVASONIC_NETWORK` env vars |
| `.env` / `.env.example` | `SILVASONIC_PODMAN_SOCKET`, `SILVASONIC_NETWORK` activated                |

---

## Phase 2: Configuration & Seeding

**Goal:** Controller bootstraps the system configuration and default microphone profiles on startup (ADR-0016, ADR-0023).

### Tasks

- [x] Create `silvasonic/controller/seeder.py` — Startup Seeding Logic
- [x] Implement `ConfigSeeder`:
  - Populates `system_config` table with missing defaults (e.g., `auto_enrollment: true`).
  - Does not overwrite values changed by the user.
- [x] Implement `ProfileBootstrapper`:
  - Reads YAML seed files from bundled `profiles/` directory.
  - Checks if a profile with the same `slug` exists in `microphone_profiles` table.
  - If it exists → skip. If not → insert.
  - Validate all seeded profiles against the `MicrophoneProfile` Pydantic schema before insertion.
- [x] Unit tests: Verify idempotence of seeders and that existing overrides are protected.

---

## Phase 3: Container Lifecycle Management & State Reconciliation

**Goal:** Controller can start, stop, list Tier 2 containers, enforce limits, and maintain desired state via reconciliation and nudges.

### Tasks — Container Management

- [x] Create Pydantic model `Tier2ServiceSpec` defining:
  - Image name, container name pattern
  - Labels (auto-populated: `io.silvasonic.tier`, `.owner`, `.service`, `.device_id`, `.profile`)
  - Environment variables, devices, mounts (with RO/RW distinction per ADR-0009)
  - Restart policy (`on-failure`, max 5 retries)
  - Network name (from `SILVASONIC_NETWORK`)
  - Resource limits: `memory_limit`, `cpu_limit`, `oom_score_adj` (ADR-0020). Recorder gets `oom_score_adj=-999`.
- [x] Create `silvasonic/controller/container_manager.py`:
  - `start(spec: Tier2ServiceSpec) → Container` — calls `podman.containers.run()` with resource limits
  - `stop(name: str)` — sends SIGTERM, waits for graceful shutdown
  - `list_managed() → list[Container]` — queries `io.silvasonic.owner=controller`
  - `reconcile()` — evaluates DB state vs Actual Podman state.

### Tasks — State Reconciliation & Nudge Subscriber (US-C03, US-C07)

- [x] Implement Device State Evaluation logic (reconcile only starts a Recorder if: `status == "online" AND enabled == true AND enrollment_status == "enrolled" AND profile_slug IS NOT NULL`).
- [x] Implement Reconciliation Loop (async, ~30s interval) to enforce the above logic.
- [x] Create `silvasonic/controller/nudge_subscriber.py`:
  - Subscribe to Redis channel `silvasonic:nudge`.
  - On receiving `"reconcile"`, immediately trigger the reconciliation logic to execute web-interface commands (e.g., enable/disable microphone).
- [x] Unit tests: mock `podman-py` & DB, verify state evaluation and start/stop/reconcile logic.

---

## Phase 4: USB Detection, HotPlug & Recorder Spawning

**Goal:** Controller detects USB microphones in near-realtime (≤ 1 s), matches profiles, and starts Recorder containers dynamically (US-C01, US-R01, US-R05).

### Tasks — USB Detection & HotPlug

- [ ] Add `pyudev` as dependency to `services/controller/pyproject.toml`
- [ ] Create `silvasonic/controller/device_scanner.py` — `DeviceScanner`
  - Enumerate ALSA cards via `/proc/asound/cards`
  - Correlate each card with USB parent via `pyudev` / `sysfs` (→ `DeviceInfo`)
  - Extract: `usb_vendor_id`, `usb_product_id`, `usb_serial`, `alsa_name`, `alsa_device`
- [ ] Create `silvasonic/controller/hotplug_monitor.py` — `HotPlugMonitor`
  - `pyudev.Monitor` (subsystem `sound`) as dedicated `asyncio.Task`
  - On `add`: scan single device, write to DB (`status=online`, `pending`), trigger reconciliation
  - On `remove`: set `status=offline`, trigger reconciliation (which will stop the recorder)
  - Latency target: ≤ 1 second. Graceful fallback to `DeviceScanner` polling if `/run/udev` missing.
- [ ] Implement stable device identity (`devices.name` as PK):
  - With USB serial: `{vendor_id}-{product_id}-{serial}` (globally unique)
  - Without serial: `{vendor_id}-{product_id}-port{bus_path}` (port-bound)

### Tasks — Profile Matching & Auto-Enrollment (US-C06)

- [ ] Create `silvasonic/controller/profile_matcher.py` — `ProfileMatcher`
  - Score 100: USB Vendor+Product ID match → Auto-Enroll (if `auto_enrollment` is true)
  - Score 50: ALSA name substring match → suggest profile (set as pending)
  - Score 0: no match → pending
- [ ] Integrate reading `auto_enrollment` flag from `system_config` table on each evaluation cycle.

### Tasks — Recorder Spawning (US-R01)

- [ ] Replace `SIMULATE_RECORDER_SPAWN` placeholder in `controller/__main__.py`
- [ ] Create `Tier2ServiceSpec` for Recorder:
  - Image: `silvasonic-recorder:latest`
  - Name pattern: `silvasonic-recorder-{device_id}`
  - Devices: `/dev/snd:/dev/snd`
  - Group add: `audio`
  - Privileged: `true` (see ADR-0007 §6)
  - Mounts: Recorder workspace = RW (producer)
  - Env vars: `RECORDER_DEVICE`, `RECORDER_PROFILE` (Profile Injection, ADR-0013)
- [ ] Connect `monitor_recorder_spawn()` to actual container health checks via `podman-py`
- [ ] Add Redis heartbeat to Recorder (fire-and-forget via `SilvaService`, ADR-0019)
- [ ] Integration test: Controller spawns Recorder container, verifies health, stops it.

---

## Phase 5: Live Log Streaming

**Goal:** Provide realtime log streaming for Tier 2 services to the Web-Interface via Redis (US-C09, ADR-0022).

### Tasks

- [ ] Create `silvasonic/controller/log_forwarder.py`
  - Continuously follow logs of running Tier 2 containers via `container.logs(stream=True)`.
  - Publish log lines as JSON to Redis channel `silvasonic:logs`.
  - Design to be resilient: automatically reconnect string if container restarts.
  - Implement fire-and-forget (if no subscribers, Redis discards the event).

---

## Phase 6: Integration & Hardening

**Goal:** End-to-end lifecycle works reliably. System survives crashes and restarts (US-C02, US-R02).

### Tasks

- [ ] Implement graceful shutdown handler in Controller (`main()`)
  - On SIGTERM: stop all owned Tier 2 containers, then exit
- [ ] Test crash recovery: kill Controller, verify Recorder keeps running (Podman manages restart limit).
- [ ] Test reconciliation: restart Controller, verify it adopts existing Recorder without restarting it.
- [ ] Test multi-instance: start 2 Recorders for different devices, verify labels and isolated file structures.
- [ ] Update smoke tests to verify Controller ↔ Recorder lifecycle.
- [ ] Update `ROADMAP.md`: mark v0.3.0 as 🔨 In Progress.

---

## Out of Scope (Deferred)

| Item                                            | Target Version |
| ----------------------------------------------- | -------------- |
| Actual audio recording (`recorder/__main__.py`) | v0.4.0         |
| Uploader, BirdNET, BatDetect as Tier 2          | v0.6.0+        |
| Icecast live Opus stream (Recorder → Icecast)   | v0.9.0         |
| Quadlet generation for production               | v1.0.0         |

> **Note:** Resource limits (CPU/RAM) and QoS (`oom_score_adj`) are now **in scope** for Phase 3 as part of the `Tier2ServiceSpec` model. See [ADR-0020](../adr/0020-resource-limits-qos.md).
>
> **Note:** USB HotPlug detection (≤ 1 s latency via `pyudev.Monitor`) is now **in scope** for Phase 4.
>
> **Note:** Live Log Streaming via Redis Pub/Sub has been added as Phase 5.
>
> **Note:** Configuration Seeding (DB bootstrapper) has been added as Phase 2.
