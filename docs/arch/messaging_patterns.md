# Messaging Patterns & Protocols

> **STATUS:** NORMATIVE (Mandatory)
> **SCOPE:** System-wide inter-service communication

This document defines the communication standards within Silvasonic — how services discover work, exchange status, and receive commands.

---

## 1. Architectural Decision: Hybrid Communication

To satisfy **Data Capture Integrity**, the system employs a **Hybrid Architecture** that separates the critical recording/analysis path from the interactive UI path.

### 1.1. The Critical Path (Polling)

**Philosophy:** The Filesystem and Database are the Source of Truth. No message broker dependency.

*   **Recorder → Processor:** **Filesystem Polling.** The Processor watches the Recorder's workspace directories for new audio files and indexes them into the `recordings` table.
*   **Processor → Workers:** **Database Polling.** Workers (BirdNET, BatDetect) independently poll the `recordings` table for unanalyzed files using `SELECT ... FOR UPDATE SKIP LOCKED`. See [ADR-0018](../adr/0018-worker-pull-orchestration.md).

> [!TIP]
> The critical path has **zero dependency on Redis**. If Redis goes down, recording, ingestion, and analysis continue uninterrupted.

### 1.2. The Interactive Path (Redis, v0.2.0+)

**Philosophy:** Responsiveness for the User Interface. Best-effort, but reliable in practice (Redis is as stable as the database on this hardware).

*   **Service Heartbeats → Web-Interface:** Every service publishes periodic heartbeats to Redis. The Web-Interface uses the **Read + Subscribe Pattern** for real-time display (see §4).
*   **Service Control → Controller API:** The Web-Interface sends control commands (stop, restart, reconcile) to the Controller's operational API via HTTP. The Controller executes them via Podman. See [ADR-0017](../adr/0017-service-state-management.md).

> [!IMPORTANT]
> The interactive path is **best-effort**. If Redis is unavailable, the Web-Interface loses real-time status, but all critical operations (recording, analysis, upload) continue via the filesystem/DB path.

---

## 2. Service State: Desired vs. Actual

See [ADR-0017](../adr/0017-service-state-management.md) for the full decision.

| Dimension                  | Storage                                    | Written By                        | Read By       |
| -------------------------- | ------------------------------------------ | --------------------------------- | ------------- |
| **Desired State** (config) | `system_services` table (DB)               | Admin / Web-Interface             | Controller    |
| **Actual State** (runtime) | Redis: `SET` with TTL + `PUBLISH` (see §3) | Each service (via `SilvaService`) | Web-Interface |

---

## 3. Redis Usage — Minimal and Unified

> **Status:** Planned (v0.2.0)

Redis serves exactly **two purposes** for Silvasonic:

| Mechanism                     | Redis Command                             | Purpose                                                     |
| :---------------------------- | :---------------------------------------- | :---------------------------------------------------------- |
| **Current Status** (snapshot) | `SET silvasonic:status:<id> <json> EX 30` | Readable anytime. 30s TTL — key disappears if service stops |
| **Live Updates** (push)       | `PUBLISH silvasonic:status <json>`        | Real-time notification for subscribers (Web-Interface)      |

No Redis Streams, no Consumer Groups, no additional channels.

### Instance ID Convention

Services are identified by a combination of `service` (type) and `instance_id` (unique instance):

| Service Type              | `instance_id`            | Key Example                        |
| ------------------------- | ------------------------ | ---------------------------------- |
| Tier 1 Singletons         | `= service name`         | `silvasonic:status:controller`     |
| Recorder (multi-instance) | `= devices.name`         | `silvasonic:status:ultramic-01`    |
| Uploader (multi-instance) | `= storage_remotes.slug` | `silvasonic:status:nextcloud-main` |
| Tier 2 Singletons         | `= service name`         | `silvasonic:status:birdnet`        |

---

## 4. Read + Subscribe Pattern

The Web-Interface uses a two-step pattern to ensure no heartbeats are missed:

```
1. On page load:   KEYS silvasonic:status:*  →  read all current statuses
2. Then:           SUBSCRIBE silvasonic:status  →  receive live updates
```

This solves the inherent problem of Pub/Sub (fire-and-forget): if the Web-Interface subscribes *after* a heartbeat was published, it would miss the latest status. The `SET` with TTL ensures the current snapshot is always available.

---

## 5. Heartbeat Payload Schema

> **Status:** Planned (v0.2.0)

**Every** service uses the same JSON schema, published by the `SilvaService` base class (see [ADR-0019](../adr/0019-unified-service-infrastructure.md)):

```json
{
  "service": "recorder",
  "instance_id": "ultramic-01",
  "timestamp": 1706612400.123,
  "health": {
    "status": "ok",
    "components": {
      "recording": { "healthy": true, "details": "" },
      "disk_space": { "healthy": true, "details": "82% free" }
    }
  },
  "activity": "recording",
  "meta": { "db_level": -45.2 }
}
```

All payloads **MUST** be valid JSON and validated via Pydantic models (see [ADR-0012](../adr/0012-use-pydantic.md)).

---

## 6. Control Flow

Control commands are routed through the **Controller's operational API** (HTTP), not through Redis:

```
┌──────────────────────────────────────────────────────────────────┐
│  Config Change (eventual consistency, ~30s)                      │
│                                                                  │
│  Web-Interface ──[DB Write]──► Database                          │
│  Controller ──[Reconciliation Loop, 30s]──► reads DB, acts       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Immediate Action (request-response)                             │
│                                                                  │
│  Web-Interface ──[HTTP POST]──► Controller API                   │
│  Controller ──[podman-py]──► Podman ──► Target Container         │
└──────────────────────────────────────────────────────────────────┘
```

> [!NOTE]
> Immutable services (Recorder, Workers, Processor) do not process runtime commands. To change their configuration, the Controller stops and restarts them with updated environment variables.

---

## 7. Communication Flow Overview

```
┌─────────────────────────────────────────────────────────────┐
│ CRITICAL PATH (Filesystem + DB — no Redis dependency)       │
│                                                             │
│  Recorder ──[WAV files]──► Processor ──[DB INSERT]──► DB    │
│                                                             │
│  BirdNET ──[SELECT FOR UPDATE SKIP LOCKED]──► DB            │
│  BatDetect ──[SELECT FOR UPDATE SKIP LOCKED]──► DB          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ INTERACTIVE PATH (Redis + Controller API, v0.2.0+)         │
│                                                             │
│  All Services ──[heartbeat]──► Redis ──► Web-Interface      │
│  Web-Interface ──[HTTP]──► Controller API ──► Podman        │
└─────────────────────────────────────────────────────────────┘
```

---

## See Also

*   [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
*   [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)
*   [ADR-0019: Unified Service Infrastructure](../adr/0019-unified-service-infrastructure.md)
*   [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
*   [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md)
*   [Filesystem Governance](filesystem_governance.md)
