# silvasonic-controller

> **Status:** Partial (since v0.1.0) · **Tier:** 1 (Infrastructure) · **Instances:** Single · **Port:** 9100
>
> 📋 **User Stories:** [controller.md](../../docs/user_storys/controller.md)

**AS-IS:** The Controller is the central orchestration service of the Silvasonic system. It detects USB microphones, evaluates the device inventory against the configuration catalog, and manages Tier 2 container lifecycles (start / stop / reconcile) via the Podman REST API (`podman-py`). It follows the **State Reconciliation Pattern** — a pure Listener + Actor with no HTTP API beyond `/healthy`.

---

## The Problem / The Gap

*   **Dynamic Hardware:** A static `compose.yml` cannot handle USB microphones being plugged/unplugged. Each physical microphone must be bound to a dedicated Recorder instance with the appropriate Microphone Profile.
*   **Self-Healing:** If a Recorder crashes, something must detect it and restart it intelligently — verifying the microphone is still present and the device is still enrolled before restarting.
*   **Orchestration:** Users need to toggle services (e.g., "Enable BirdNET", "Disable Weather") via the Web-Interface without SSH access. The Controller bridges this gap via the State Reconciliation Pattern.

## User Benefit

*   **Plug-and-Play:** Automatically detects connected microphones within **≤ 1 second** (via `pyudev` HotPlug events) and spins up the appropriate Recorder containers with the correct configuration (Profile Injection).
*   **Resilience:** Automatically repairs broken services via the reconciliation loop (~30s). A disconnected microphone is detected within 1 second and its Recorder is stopped cleanly.
*   **Control:** Allows enabling/disabling features via the Web-Interface to save power, CPU, or storage — all routed through DB desired state, never direct commands.

---

## Responsibility Split

| Concept                   | DB Table              | Role                                                                                                       |
| ------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Device Inventory**      | `devices`             | Tracks *what* hardware is plugged in — serial number, model, administrative state (`enrollment_status`).   |
| **Configuration Catalog** | `microphone_profiles` | Defines *how* a Recorder should behave for a given class of device — sample rate, channels, match pattern. |

The Controller reads both tables and decides which Recorders to start.

---

## Startup & Seeding

> **Status:** 🔮 Planned (v0.3.0) · **User Stories:** [US-C06](../../docs/user_storys/controller.md#us-c06-mikrofon-profile-verwalten-), [US-C08](../../docs/user_storys/controller.md#us-c08-funktioniert-sofort-nach-installation-)

On every startup, the Controller runs two idempotent seeders in sequence:

### 1. Config Seeder

Populates `system_config` with default key-value pairs (e.g., `auto_enrollment: true`, `device_name`). Each key is only inserted if it does **not** already exist — user-modified values are never overwritten.

### 2. Profile Bootstrapper

Reads YAML seed files from the bundled `profiles/` directory and writes them to the `microphone_profiles` table:

*   For each seed file, check if a profile with the same `slug` already exists in the DB.
*   **Exists → skip.** This protects user-created or user-modified profiles.
*   **Does not exist → insert** the system profile.

All profiles (seed and user-created) are validated against the [`MicrophoneProfile` Pydantic schema](../../packages/core/src/silvasonic/core/schemas/devices.py) before being persisted. Invalid profiles are rejected with an error in the log.

### After a Database Reset

If the database is wiped, the next Controller startup restores all defaults automatically — the system is immediately operational again (see [ADR-0023](../../docs/adr/0023-configuration-management.md)).

---

## Device State Evaluation

> **Status:** 🔮 Planned (v0.3.0 Phase 2)

The Controller starts a Recorder for a Device **only** when all of the following conditions are met:

```
status == "online"
AND enabled == true
AND enrollment_status == "enrolled"
AND profile_slug IS NOT NULL (valid FK to microphone_profiles)
```

If any condition is not met, the Controller will not start (or will stop) the Recorder for that Device.

### Enrollment State Machine

| Transition           | Payload Effect                                       | Controller Action                                            |
| -------------------- | ---------------------------------------------------- | ------------------------------------------------------------ |
| **Enroll**           | `enrollment_status → enrolled`, `profile_slug` set   | Next reconcile loop starts a Recorder for this Device.       |
| **Unenroll / Reset** | `enrollment_status → pending`, `profile_slug → null` | Controller stops the running Recorder immediately.           |
| **Ignore**           | `enrollment_status → ignored`                        | Controller suppresses logs for this Device, never starts it. |
| **Emergency Stop**   | `enabled → false`                                    | Immediate stop, regardless of enrollment status.             |

### Enrollment Status Values

| Value      | Meaning                                                             |
| ---------- | ------------------------------------------------------------------- |
| `pending`  | New device detected, not yet assigned a profile. Default state.     |
| `enrolled` | Assigned a Microphone Profile. Eligible for recording.              |
| `ignored`  | Suppressed. Controller will never start a Recorder for this device. |

---

## USB Detection & HotPlug

> **Status:** 🔮 Planned (v0.3.0 Phase 3)

The Controller detects **all** USB audio devices on the host — not only those with a known Microphone Profile. Detection uses a two-layer architecture:

### Layer 1: Event-Driven HotPlug (Primary, ≤ 1 s)

A `pyudev.Monitor` (subsystem `sound`) runs as a dedicated `asyncio.Task` and listens for Linux kernel `udev` events:

*   **`add` event:** A new ALSA sound card appears → Controller scans the device, correlates USB metadata, writes to DB, and triggers an immediate reconciliation.
*   **`remove` event:** An ALSA card disappears → Controller sets `status=offline`, stops the associated Recorder (SIGTERM), and triggers reconciliation.

**Timing:** USB plug → kernel detects (~50 ms) → udev event (~100 ms) → `pyudev.Monitor` receives (~150 ms) → DB write + reconcile trigger (~300 ms) → **total < 1 second**.

### Layer 2: Full Scan (Fallback, ~30 s)

A `DeviceScanner` runs inside the existing reconciliation loop as a safety net:

*   Enumerates all ALSA cards via `/proc/asound/cards`.
*   Correlates each card with its USB parent via `pyudev` / `sysfs`.
*   Detects devices that the Monitor may have missed (e.g., devices plugged in before the Controller started, or if `udev` is unavailable inside the container).

> **Graceful Degradation:** If the `pyudev.Monitor` fails to start (e.g., `/run/udev` not mounted), the Controller falls back to polling-only mode with a warning in the log. HotPlug latency increases to ~30 s, but functionality is preserved.

### USB ↔ ALSA Correlation

For each ALSA card, the Controller walks the `sysfs` tree via `pyudev` to extract stable USB identifiers:

```python
# Pseudocode: correlate ALSA card with USB device
context = pyudev.Context()
device = pyudev.Devices.from_sys_path(context, f"/sys/class/sound/card{idx}")
usb_parent = device.find_parent('usb', 'usb_device')

if usb_parent:
    vendor_id  = usb_parent.get('ID_VENDOR_ID')     # e.g., "2578"
    product_id = usb_parent.get('ID_MODEL_ID')       # e.g., "0001"
    serial     = usb_parent.get('ID_SERIAL_SHORT')   # e.g., "ABC123" (may be None!)
    vendor     = usb_parent.get('ID_VENDOR')          # e.g., "Dodotronic"
    model      = usb_parent.get('ID_MODEL')           # e.g., "Ultramic_384K"
```

Devices **without** a USB parent (e.g., the Raspberry Pi's built-in `bcm2835` audio) are registered as `pending` but will never match a profile — the user can set them to `ignored` via the Web-Interface.

---

## Device Identity & Stable Naming

> **Status:** 🔮 Planned (v0.3.0 Phase 3) · **User Story:** [US-C01](../../docs/user_storys/controller.md#us-c01-mikrofon-einstecken--sofort-erkannt-️)

Re-plugging a microphone must re-activate the same Recorder with the same workspace, storage, and identity — no duplicate Recorders. Each physical microphone is identified by a **stable device ID** that survives unplugging and re-plugging:

| Scenario                             | Identification Method                     | Stability                                  |
| ------------------------------------ | ----------------------------------------- | ------------------------------------------ |
| USB device **with** serial number    | `{vendor_id}-{product_id}-{serial}`       | ✅ Globally unique, survives port changes   |
| USB device **without** serial number | `{vendor_id}-{product_id}-port{bus_path}` | ⚠️ Stable as long as same physical USB port |

The stable device ID is stored as `devices.name` (primary key) and determines:

*   **Recorder container name:** `silvasonic-recorder-{device_id}`
*   **Workspace directory:** `workspace/recorder/{device_id}/`
*   **Redis instance ID:** `silvasonic:status:{device_id}`

This ensures that **re-plugging a microphone re-activates the same Recorder** with the same workspace, storage, and identity — no duplicate Recorders are created.

> **Note:** Not all USB devices provide a serial number. Budget USB microphones often omit it. In this case, the port-based fallback is used. Moving the microphone to a different USB port will create a new device entry (with a warning in the Web-Interface).

---

## Profile Matching & Auto-Enrollment

> **Status:** 🔮 Planned (v0.3.0 Phase 3)

When a new USB device is detected, the Controller matches it against all `microphone_profiles` using structured `MatchCriteria`:

### Match Criteria (part of the profile's `config` JSONB)

```yaml
# Example: ultramic_384_evo.yml
audio:
  match:
    usb_vendor_id: "2578"           # Primary — registered, never changes
    usb_product_id: "0001"          # Primary — together with vendor = unique device type
    alsa_name_contains: "ultramic"  # Secondary — case-insensitive substring fallback
```

### Matching Algorithm

| Score   | Condition                        | Result                                                 |
| ------- | -------------------------------- | ------------------------------------------------------ |
| **100** | USB Vendor ID + Product ID match | **Auto-Enrollment** (device is enrolled automatically) |
| **50**  | ALSA name substring match only   | **Suggestion** — user confirms in Web-Interface        |
| **0**   | No match                         | **Pending** — user selects profile manually            |

### Auto-Enrollment Setting

Auto-Enrollment is controlled by the `auto_enrollment` flag in `system_config` (key `system`). Default: `true`. Can be changed at runtime via the Web-Interface — the Controller reads this setting on every reconciliation cycle (no restart required).

When `auto_enrollment` is `false`, all new devices remain `pending` regardless of match score — the user must always confirm enrollment manually.

See [Microphone Profiles](../../docs/arch/microphone_profiles.md) for the full profile specification.

## Reconciliation Loop

> **Status:** 🔮 Planned (v0.3.0 Phase 2)

The Controller runs a periodic reconciliation loop (~30 s) that compares **desired state** (from `devices` + `microphone_profiles` tables) against **actual state** (running containers queried via Podman labels).

Every Tier 2 container is tagged with labels for lifecycle management:

```
io.silvasonic.tier: "2"
io.silvasonic.owner: "controller"
io.silvasonic.service: "recorder"
io.silvasonic.device_id: <device_id>
io.silvasonic.profile: <profile_slug>
```

On startup, the Controller queries all containers with `io.silvasonic.owner=controller` and adopts them without restarting — ensuring Data Capture Integrity across Controller restarts.

> **TO-BE:** (v0.3.0) — See [Milestone v0.3.0](../../docs/development/milestone_0_3_0.md).

---

## Profile Injection & Management

> **Status:** 🔮 Planned (v0.3.0 Phase 2) · **User Story:** [US-C06](../../docs/user_storys/controller.md#us-c06-mikrofon-profile-verwalten-)

The Recorder has **no database access** (ADR-0013). The Controller injects the Microphone Profile configuration into Recorder containers via environment variables at container creation time:

```
RECORDER_DEVICE=hw:1,0
RECORDER_PROFILE=ultramic_384_evo
```

### Seed & Protection Logic

Profiles are bootstrapped from YAML seed files into the database on every Controller startup (see §Startup & Seeding above, [ADR-0016](../../docs/adr/0016-hybrid-yaml-db-profiles.md)).

*   **KISS principle:** If a profile with the same `slug` already exists → skip. User profiles are never overwritten.
*   All profiles are validated against the [`MicrophoneProfile` Pydantic schema](../../packages/core/src/silvasonic/core/schemas/devices.py) before persistence.

See [Microphone Profiles](../../docs/arch/microphone_profiles.md) for the full profile specification.

---

## Shutdown Semantics

> **Status:** 🔮 Planned (v0.3.0 Phase 2)

| Scenario                      | Behavior                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| **Deliberate stop** (SIGTERM) | Controller stops all owned Tier 2 containers, waits for graceful shutdown, then exits.     |
| **Controller crash**          | Tier 2 containers **keep running** — Podman restart policy keeps them alive independently. |
| **Controller restart**        | Reconciles via label query, adopts existing containers without restarting them.            |

> **Priority:** Data Capture Integrity > Clean Shutdown. A Recorder must never be interrupted by a Controller restart.

---

## Reconcile-Nudge Subscriber

> **Status:** 🔮 Planned (v0.3.0)

The Controller follows the **State Reconciliation Pattern** (inspired by Kubernetes Operators). It has **no HTTP API** beyond `/healthy` — control is exclusively declarative:

1.  **Web-Interface** writes desired state to the database (e.g., `enabled=false`).
2.  **Web-Interface** sends `PUBLISH silvasonic:nudge "reconcile"` — a simple wake-up signal.
3.  **Controller** (subscribed) wakes up, reads DB, compares desired vs. actual, acts via `podman-py`.

### Control Flow

*   **All state changes** (enable/disable, change profile, emergency stop): Web-Interface → DB write → Redis nudge → Controller reconciles immediately
*   **Timer fallback**: If the nudge is lost (Controller restarting), the 30s reconciliation timer catches up automatically. The DB desired state is never lost.

See [ADR-0017](../../docs/adr/0017-service-state-management.md) and [Messaging Patterns](../../docs/arch/messaging_patterns.md).

> **TO-BE:** (v0.3.0)

---

## Redis: Heartbeat & Host Metrics

> **Status:** ✅ Implemented (v0.2.0) · **User Story:** [US-C05](../../docs/user_storys/controller.md#us-c05-systemstatus-im-dashboard-)

The Controller publishes its own heartbeat like every service (via `SilvaService`, see [ADR-0019](../../docs/adr/0019-unified-service-infrastructure.md)).

**Host Resource Monitoring:** In addition to the standard per-process `meta.resources` that every `SilvaService` includes, the Controller publishes **host-level** metrics in `meta.host_resources`:

*   Total CPU utilization and core count
*   Total RAM used/total/percent
*   Storage used/total/percent (for `SILVASONIC_WORKSPACE_PATH`)

This enables the Web-Interface dashboard to display system-wide resource gauges alongside per-service metrics. The Controller uses the `HostResourceCollector` from `silvasonic.core.resources` for this.

> **Note:** Each Tier 2 service publishes its own status independently via its own `SilvaService` heartbeat. The Controller does **not** publish on behalf of other services.

---

## Live Log Streaming

> **Status:** 🔮 Planned (v0.3.0) · **User Story:** [US-C09](../../docs/user_storys/controller.md#us-c09-dienst-logs-live-im-browser-)

The Controller forwards Tier 2 container logs to the Web-Interface via Redis Pub/Sub ([ADR-0022](../../docs/adr/0022-live-log-streaming.md)):

```
Service → stdout (structlog JSON) → Controller (podman logs --follow) → PUBLISH silvasonic:logs → Web-Interface (SSE) → Browser
```

*   The Controller reads stdout of each managed container via `podman logs --follow`.
*   Each log line is published as JSON to the `silvasonic:logs` Redis channel.
*   **Fire-and-forget:** If no subscriber is connected, log messages are simply discarded (no backpressure, no persistence).
*   The Web-Interface subscribes and delivers logs to the browser via Server-Sent Events (SSE).

---

## Resource Limits & QoS Enforcement

> **Status:** 🔮 Planned (v0.3.0 Phase 2)

The Controller enforces **mandatory resource limits** on every Tier 2 container it spawns:

### Container Operational Constraints & Rules

Specific technical rules the Controller must obey:

*   **Concurrency**: **Single Control Loop**. Avoids race conditions by serializing orchestration actions.
*   **State**: **Stateless** (Authority is DB + Podman states).
*   **Privileges**: **High Privilege**. Requires access to Podman Socket (Group `podman`).

| Parameter       | Purpose                                | Example Values                     |
| --------------- | -------------------------------------- | ---------------------------------- |
| `mem_limit`     | Hard memory cap (cgroups v2)           | `512m`, `1g`                       |
| `cpu_quota`     | CPU time cap (microseconds per period) | `100000` (= 1.0 CPU)               |
| `oom_score_adj` | OOM Killer priority (-999 to +500)     | `-999` (Recorder), `500` (BirdNET) |

**OOM Priority Hierarchy:**

| Priority         | `oom_score_adj` | Services                    |
| ---------------- | --------------- | --------------------------- |
| **Protected**    | `-999`          | Recorder                    |
| **Default**      | `0`             | Tier 1 infrastructure       |
| **Low Priority** | `250`           | Uploader                    |
| **Expendable**   | `500`           | BirdNET, BatDetect, Weather |

The Recorder's `oom_score_adj=-999` ensures it is the **last** process the Linux OOM Killer targets. This is the final line of defense for Data Capture Integrity.

Resource limit fields (`memory_limit`, `cpu_limit`, `oom_score_adj`) are part of the `Tier2ServiceSpec` Pydantic model. See [ADR-0020](../../docs/adr/0020-resource-limits-qos.md).

---

## Implementation Status

| Feature                              | Status                                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Health monitoring                    | ✅ Implemented (database connectivity, recorder spawn placeholder)                                       |
| Redis heartbeat + host metrics       | ✅ Implemented (SilvaService base, host_resources via HostResourceCollector)                             |
| Podman socket connection             | 🔮 Planned (v0.3.0 Phase 1)                                                                              |
| Container lifecycle mgmt             | 🔮 Planned (v0.3.0 Phase 2)                                                                              |
| Reconciliation loop                  | 🔮 Planned (v0.3.0 Phase 2)                                                                              |
| Config seeder + profile bootstrapper | 🔮 Planned (v0.3.0, ADR-0016/0023) — System defaults + profile seeds, no admin account (→ Web-Interface) |
| USB detection (`pyudev`)             | 🔮 Planned (v0.3.0 Phase 3)                                                                              |
| HotPlug Monitor (`pyudev`)           | 🔮 Planned (v0.3.0 Phase 3)                                                                              |
| Profile matching + enroll            | 🔮 Planned (v0.3.0 Phase 3)                                                                              |
| Reconcile-nudge subscriber           | 🔮 Planned (v0.3.0)                                                                                      |
| Log forwarding (Podman→Redis)        | 🔮 Planned (v0.3.0, ADR-0022)                                                                            |

---

## Technology Stack

*   **Container Management:** `podman-py` (Podman REST API client)
*   **Hardware Detection:** `pyudev` (Linux `udev` / `libudev` bindings for USB enumeration + HotPlug monitoring)
*   **Database:** `sqlalchemy` (2.0+ async), `asyncpg`
*   **Redis:** `redis-py` (async, for heartbeats + nudge subscription)
*   **Config:** `pydantic` (Tier2ServiceSpec model, Microphone Profiles)
*   **Core:** `silvasonic.core.service.SilvaService` (base class for Health check and Redis Publisher)
*   **Base Image:** `python:3.11-slim-bookworm` (Dockerfile)

---

## Out of Scope

*   **Does NOT** process audio data (Recorder + Processor's job).
*   **Does NOT** serve the User Interface (Web-Interface's job).
*   **Does NOT** store business data persistently (Database's job).
*   **Does NOT** perform heavy inference (BirdNET / BatDetect's job).
*   **Does NOT** expose an HTTP API beyond `/healthy` — CRUD operations are handled by the Web-Interface (FastAPI + Swagger, see [ADR-0003](../../docs/adr/0003-frontend-architecture.md)). Control actions are routed declaratively via DB + Redis nudge (see §Reconcile-Nudge Subscriber above).

---

## Configuration

| Variable / Mount             | Description                               | Default / Example                                                 |
| ---------------------------- | ----------------------------------------- | ----------------------------------------------------------------- |
| `SILVASONIC_CONTROLLER_PORT` | Health endpoint port                      | `9100`                                                            |
| `CONTAINER_SOCKET`           | Podman socket path inside container       | `/var/run/container.sock`                                         |
| `SILVASONIC_NETWORK`         | Podman network name for Tier 2 containers | `silvasonic-net`                                                  |
| Socket mount                 | Host Podman socket bind mount             | `${SILVASONIC_PODMAN_SOCKET}:/var/run/container.sock:z`           |
| udev mount                   | Host udev runtime for HotPlug events      | `/run/udev:/run/udev:ro`                                          |
| Workspace mount              | Controller workspace                      | `${SILVASONIC_WORKSPACE_PATH}/controller:/app/workspace:z`        |
| Recorder workspace mount     | Recorder workspace (for provisioning)     | `${SILVASONIC_WORKSPACE_PATH}/recorder:/app/recorder-workspace:z` |

---

## References

- [ADR-0013: Tier 2 Container Management](../../docs/adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profile Management](../../docs/adr/0016-hybrid-yaml-db-profiles.md)
- [ADR-0017: Service State Management](../../docs/adr/0017-service-state-management.md)
- [ADR-0019: Unified Service Infrastructure](../../docs/adr/0019-unified-service-infrastructure.md)
- [ADR-0020: Resource Limits & QoS](../../docs/adr/0020-resource-limits-qos.md)
- [Milestone v0.3.0](../../docs/development/milestone_0_3_0.md) — Step-by-step implementation plan
- [Messaging Patterns](../../docs/arch/messaging_patterns.md) — State Reconciliation Pattern, Nudge
- [Port Allocation](../../docs/arch/port_allocation.md) — Controller on port 9100
- [Microphone Profiles](../../docs/arch/microphone_profiles.md) — Profile seed files
- [Glossary](../../docs/glossary.md) — canonical definitions
- [VISION.md](../../VISION.md) — services architecture
