# silvasonic-controller

> **Tier:** 1 (Infrastructure) · **Instances:** Single · **Port:** 9100

The Controller is the central orchestration service of the Silvasonic system. It detects USB microphones, evaluates the device inventory against the configuration catalog, and manages Tier 2 container lifecycles (start / stop / reconcile) via the Podman REST API (`podman-py`).

> **Implementation Status:** Scaffold (v0.1.0). Health monitoring is implemented. Tier 2 management is planned for v0.2.0.

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

> **⏳ Planned** (v0.2.0) — See [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md).

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

## Implementation Status

| Feature                  | Status                                                            |
| ------------------------ | ----------------------------------------------------------------- |
| Health monitoring        | ✅ Implemented (database connectivity, recorder spawn placeholder) |
| Podman socket connection | ⏳ Planned (v0.2.0 Phase 1)                                        |
| Container lifecycle mgmt | ⏳ Planned (v0.2.0 Phase 2)                                        |
| USB microphone detection | ⏳ Planned (v0.2.0 Phase 3)                                        |
| Reconciliation loop      | ⏳ Planned (v0.2.0 Phase 2)                                        |
| Profile bootstrapper     | ⏳ Planned (ADR-0016)                                              |

---

## References

- [ADR-0013: Tier 2 Container Management](../../docs/adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profile Management](../../docs/adr/0016-hybrid-yaml-db-profiles.md)
- [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md) — Step-by-step implementation plan
- [Port Allocation](../../docs/arch/port_allocation.md) — Controller on port 9100
- [Microphone Profiles](../../docs/arch/microphone_profiles.md)
