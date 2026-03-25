# Milestone v0.3.0 — Tier 2 Container Management

> **Target:** v0.3.0 — Controller manages Recorder lifecycle (start/stop), Hardware Detection, State Reconciliation & Log Streaming
>
> **Status:** ✅ Complete — All Phases (1–6) done
>
> **References:** [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0007 §6](../adr/0007-rootless-os-compliance.md), [ADR-0009](../adr/0009-zero-trust-data-sharing.md), [VISION.md](../../VISION.md), [Controller README](../../services/controller/README.md), [Recorder README](../../services/recorder/README.md)
>
> **User Stories:** [US-C01](../user_stories/controller.md#us-c01), [US-C02](../user_stories/controller.md#us-c02), [US-C03](../user_stories/controller.md#us-c03), [US-C04](../user_stories/controller.md#us-c04), [US-C06](../user_stories/controller.md#us-c06), [US-C07](../user_stories/controller.md#us-c07), [US-C08](../user_stories/controller.md#us-c08), [US-C09](../user_stories/controller.md#us-c09), [US-R01](../user_stories/recorder.md#us-r01), [US-R02](../user_stories/recorder.md#us-r02), [US-R05](../user_stories/recorder.md#us-r05)

---

## Phase 1: Controller ↔ Podman Socket Connection

**Goal:** Controller connects to the host Podman engine and can list running containers.

### Tasks

- [x] Add `podman-py` as dependency to `services/controller/pyproject.toml`
- [x] Create `silvasonic/controller/podman_client.py` — PodmanClient wrapper
  - Connect to socket (`SILVASONIC_CONTAINER_SOCKET` env var, default `/var/run/container.sock`)
  - `ping()` health check on startup
  - Reconnect logic (socket may not be available immediately)
- [x] Verify socket mount works in `compose.yml` (`${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z`)
- [x] Unit test: mock PodmanClient, verify connection logic
- [x] Integration test: Controller container connects to host Podman, lists containers

### Config Changes (✅ Already Applied)

| File                    | Change                                                                    |
| ----------------------- | ------------------------------------------------------------------------- |
| `compose.yml`           | Socket volume mount, `SILVASONIC_CONTAINER_SOCKET` and `SILVASONIC_NETWORK` env vars |
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
- [x] Implement `AuthSeeder` (ADR-0023 §2.4, US-C08):
  - Reads `auth` section from `config/defaults.yml` (default_username, default_password).
  - Checks if user with same username already exists → skip.
  - Hashes password with `bcrypt` before insertion into `users` table.
  - Existing user accounts are **never** overwritten (idempotent).
- [x] Unit tests: Verify idempotence of seeders and that existing overrides are protected.
- [x] Unit tests: AuthSeeder — admin creation with bcrypt hash, skip existing, missing file, no auth section, invalid YAML (5 tests).
- [x] Integration test: AuthSeeder inserts admin user with bcrypt hash into real PostgreSQL.

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
- [x] Implement Reconciliation Loop (async, configurable interval) to enforce the above logic.
- [x] Create `silvasonic/controller/nudge_subscriber.py`:
  - Subscribe to Redis channel `silvasonic:nudge`.
  - On receiving `"reconcile"`, immediately trigger the reconciliation logic to execute web-interface commands (e.g., enable/disable microphone).
- [x] Unit tests: mock `podman-py` & DB, verify state evaluation and start/stop/reconcile logic.

---

## Phase 4: USB Detection & Recorder Spawning

**Goal:** Controller detects USB microphones within ≤ 1 s (polling), matches profiles, and starts Recorder containers dynamically (US-C01, US-R01, US-R05).

### Tasks — USB Detection

- [x] Create `silvasonic/controller/device_scanner.py` — `DeviceScanner`
  - Enumerate ALSA cards via `/proc/asound/cards`
  - Correlate each card with USB parent via `sysfs` / `pathlib` (→ `DeviceInfo`)
  - Extract: `usb_vendor_id`, `usb_product_id`, `usb_serial`, `alsa_name`, `alsa_device`
- [x] Implement stable device identity (`devices.name` as PK):
  - With USB serial: `{vendor_id}-{product_id}-{serial}` (globally unique)
  - Without serial: `{vendor_id}-{product_id}-port{bus_path}` (port-bound)
  - Fallback: `alsa-card{index}` (unstable across reboots)
- [x] Implement `upsert_device()` — insert-or-update device in `devices` table
- [x] Integrate hardware rescan into Reconciliation Loop (`_rescan_hardware()` — runs every cycle)
- [x] Implement disconnect detection: devices no longer found are marked `status=offline`
- [x] Unit tests: `DeviceInfo.stable_device_id`, `parse_asound_cards`, `DeviceScanner.scan_all`, `upsert_device` (22 tests, all passing)

### Tasks — Profile Matching & Auto-Enrollment (US-C06)

- [x] Create `silvasonic/controller/profile_matcher.py` — `ProfileMatcher`
  - Score 100: USB Vendor+Product ID match → Auto-Enroll (if `auto_enrollment` is true)
  - Score 50: ALSA name substring match → suggest profile (set as pending)
  - Score 0: no match → pending
- [x] Integrate reading `auto_enrollment` flag from `system_config` table on each evaluation cycle.
- [x] Unit tests: exact match, ALSA match, no match, auto_enrollment=false, case-insensitive, empty profiles (7 tests)

### Tasks — Recorder Spawning (US-R01)

- [x] Create `build_recorder_spec()` factory function in `container_spec.py`:
  - Image: `localhost/silvasonic_recorder:latest`
  - Name pattern: `silvasonic-recorder-{slug}-{suffix}` (z.B. `silvasonic-recorder-ultramic-384-evo-034f`)
  - Devices: `/dev/snd:/dev/snd`
  - Group add: `audio`
  - Privileged: `true` (see ADR-0007 §6)
  - Mounts: Recorder workspace = RW (producer), with `controller_source` for mkdir
  - Env vars: `SILVASONIC_RECORDER_DEVICE`, `SILVASONIC_RECORDER_PROFILE_SLUG`, `SILVASONIC_REDIS_URL`, `SILVASONIC_INSTANCE_ID` (Profile Injection, ADR-0013)
  - Resource limits from env vars with defaults (`512m`, `1.0` CPU, `oom_score_adj=-999`)
- [x] Connect Recorder spawning to reconciliation loop (DeviceStateEvaluator → build_recorder_spec → ContainerManager.reconcile)
- [x] Add Redis heartbeat to Recorder (fire-and-forget via `SilvaService` base class, ADR-0019)
- [x] Integration test: Controller spawns Recorder container, verifies health, stops it.

---

## Phase 5: Live Log Streaming

**Goal:** Provide realtime log streaming for Tier 2 services to the Web-Interface via Redis (US-C09, ADR-0022).

### Tasks

- [x] Create `silvasonic/controller/log_forwarder.py`
  - Continuously follow logs of running Tier 2 containers via `container.logs(stream=True)`.
  - Publish log lines as JSON to Redis channel `silvasonic:logs`.
  - Design to be resilient: automatically reconnect string if container restarts.
  - Implement fire-and-forget (if no subscribers, Redis discards the event).
- [x] Unit tests: `_parse_log_line`, `_sync_follow_tasks`, `run()` main loop, `_follow_container` error handling, `_cancel_all_tasks` (26 tests, 98% coverage)
- [x] Integration tests: LogForwarder ↔ real Redis Pub/Sub — publish, non-JSON fallback, container removal, graceful shutdown (4 tests)

---

## Phase 6: Integration & Hardening

**Goal:** End-to-end lifecycle works reliably. System survives crashes and restarts (US-C02, US-R02).

### Tasks

- [x] Implement graceful shutdown handler in Controller (`run()`)
  - On SIGTERM: stop all owned Tier 2 containers, then exit
  - `_stop_all_tier2()` method queries `list_managed()` and stops each container before closing the Podman client.
- [x] Test crash recovery: kill Controller, verify Recorder keeps running (Podman manages restart limit).
- [x] Test reconciliation: restart Controller, verify it adopts existing Recorder without restarting it.
- [x] Test multi-instance: start 2 Recorders for different devices, verify labels and isolated file structures.
- [x] ~~Update smoke tests~~ — N/A: smoke test Controller lacks Podman socket (DooD). Lifecycle is fully covered by `test_crash_recovery.py` against real Podman (3 tests, 33s).

---

## Out of Scope (Deferred)

| Item                                            | Target Version |
| ----------------------------------------------- | -------------- |
| Actual audio recording (`recorder/__main__.py`) | v0.4.0         |
| Uploader, BirdNET, BatDetect as Tier 2          | v0.6.0+        |
| Icecast live Opus stream (Recorder → Icecast)   | v1.1.0         |
| Quadlet generation for production               | v1.0.0         |

> **Note:** Resource limits (CPU/RAM) and QoS (`oom_score_adj`) are now **in scope** for Phase 3 as part of the `Tier2ServiceSpec` model. See [ADR-0020](../adr/0020-resource-limits-qos.md).

>
> **Note:** Live Log Streaming via Redis Pub/Sub has been added as Phase 5.
>
> **Note:** Configuration Seeding (DB bootstrapper) has been added as Phase 2.
>
> **Note:** USB detection uses `sysfs` / `pathlib` directly (no `pyudev` dependency).
