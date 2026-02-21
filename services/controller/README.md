# silvasonic-controller

> **Tier:** 1 (Infrastructure) · **Instances:** Single · **Port:** 9100

The Controller is the central orchestration service of the Silvasonic system. It detects USB microphones, evaluates the device inventory against the configuration catalog, and manages Tier 2 container lifecycles (start / stop / reconcile) via the Podman REST API (`podman-py`). It follows the **State Reconciliation Pattern** — a pure Listener + Actor with no HTTP API beyond `/healthy`.

> **Implementation Status:** Scaffold (v0.1.0). Health monitoring is implemented. Tier 2 management is planned for v0.3.0.

---

## Responsibility Split

| Concept                   | DB Table              | Role                                                                                                       |
| ------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Device Inventory**      | `devices`             | Tracks *what* hardware is plugged in — serial number, model, administrative state (`enrollment_status`).   |
| **Configuration Catalog** | `microphone_profiles` | Defines *how* a Recorder should behave for a given class of device — sample rate, channels, match pattern. |

The Controller reads both tables and decides which Recorders to start.

---

## Device State Evaluation

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

## Reconciliation Loop

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

> **⏳ Planned** (v0.3.0) — See [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md).

---

## Profile Injection

The Recorder has **no database access** (ADR-0013). The Controller injects the Microphone Profile configuration into Recorder containers via environment variables at container creation time:

```
RECORDER_DEVICE=hw:1,0
RECORDER_PROFILE=ultramic_384_evo
```

Profiles are bootstrapped from YAML seed files into the database on every Controller startup (ADR-0016).

---

## Shutdown Semantics

| Scenario                      | Behavior                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| **Deliberate stop** (SIGTERM) | Controller stops all owned Tier 2 containers, waits for graceful shutdown, then exits.     |
| **Controller crash**          | Tier 2 containers **keep running** — Podman restart policy keeps them alive independently. |
| **Controller restart**        | Reconciles via label query, adopts existing containers without restarting them.            |

> **Priority:** Data Capture Integrity > Clean Shutdown. A Recorder must never be interrupted by a Controller restart.

---

## Reconcile-Nudge Subscriber

The Controller follows the **State Reconciliation Pattern** (inspired by Kubernetes Operators). It has **no HTTP API** beyond `/healthy` — control is exclusively declarative:

1.  **Web-Interface** writes desired state to the database (e.g., `enabled=false`).
2.  **Web-Interface** sends `PUBLISH silvasonic:nudge "reconcile"` — a simple wake-up signal.
3.  **Controller** (subscribed) wakes up, reads DB, compares desired vs. actual, acts via `podman-py`.

### Control Flow

*   **All state changes** (enable/disable, change profile, emergency stop): Web-Interface → DB write → Redis nudge → Controller reconciles immediately
*   **Timer fallback**: If the nudge is lost (Controller restarting), the 30s reconciliation timer catches up automatically. The DB desired state is never lost.

See [ADR-0017](../../docs/adr/0017-service-state-management.md) and [Messaging Patterns](../../docs/arch/messaging_patterns.md).

> ⏳ **Planned** (v0.3.0)

---

## Redis: Heartbeat + Status Aggregator

The Controller publishes its own heartbeat like every service (via `SilvaService`, see [ADR-0019](../../docs/adr/0019-unified-service-infrastructure.md)).

Additionally, it acts as a **status aggregator** for Tier 2 containers that may not have established their Redis connection yet (e.g., during startup). The Controller queries Tier 2 health endpoints via `podman-py` and publishes their status to Redis on their behalf until they report independently.

---

## Resource Limits & QoS Enforcement

The Controller enforces **mandatory resource limits** on every Tier 2 container it spawns:

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

| Feature                  | Status                                                            |
| ------------------------ | ----------------------------------------------------------------- |
| Health monitoring        | ✅ Implemented (database connectivity, recorder spawn placeholder) |
| Podman socket connection | ⏳ Planned (v0.3.0 Phase 1)                                        |
| Container lifecycle mgmt | ⏳ Planned (v0.3.0 Phase 2)                                        |
| USB microphone detection | ⏳ Planned (v0.3.0 Phase 3)                                        |
| Reconciliation loop      | ⏳ Planned (v0.3.0 Phase 2)                                        |
| Profile bootstrapper     | ⏳ Planned (ADR-0016)                                              |
| Reconcile-nudge sub.     | ⏳ Planned (v0.3.0)                                                |
| Redis heartbeat + agg.   | ⏳ Planned (v0.2.0, ADR-0019)                                      |

---

The Controller has **no HTTP API** beyond the `/healthy` health endpoint (from `SilvaService`). CRUD operations on Devices, Profiles, and configuration are handled by the **Web-Interface** service (FastAPI + Swagger, see [ADR-0003](../../docs/adr/0003-frontend-architecture.md)). Control actions are routed declaratively via DB + Redis nudge (see §Reconcile-Nudge Subscriber above).

## Configuration

| Variable                     | Description                               | Default                   |
| ---------------------------- | ----------------------------------------- | ------------------------- |
| `SILVASONIC_CONTROLLER_PORT` | Health endpoint port                      | `9100`                    |
| `CONTAINER_SOCKET`           | Path to Podman socket inside container    | `/var/run/container.sock` |
| `SILVASONIC_NETWORK`         | Podman network name for Tier 2 containers | `silvasonic-net`          |

---

## References

- [ADR-0013: Tier 2 Container Management](../../docs/adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profile Management](../../docs/adr/0016-hybrid-yaml-db-profiles.md)
- [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md) — Step-by-step implementation plan
- [Port Allocation](../../docs/arch/port_allocation.md) — Controller on port 9100
- [Microphone Profiles](../../docs/arch/microphone_profiles.md)
