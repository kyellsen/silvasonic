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

### 1.2. The Interactive Path (Redis Pub/Sub, v0.6.0)

**Philosophy:** Responsiveness for the User Interface. Ephemeral, best-effort.

*   **Service Heartbeats → Web-Interface:** **Redis Pub/Sub** (`silvasonic.status`). Each service publishes periodic heartbeats; the Web-Interface subscribes for real-time display.
*   **Service Control:** **Redis Streams** (`stream:control`). The Web-Interface publishes commands (e.g., restart service); targeted services consume and execute them.

> [!IMPORTANT]
> The interactive path is **best-effort**. If Redis is unavailable, the Web-Interface loses real-time status, but all critical operations (recording, analysis, upload) continue via the filesystem/DB path.

---

## 2. Service State: Desired vs. Actual

See [ADR-0017](../adr/0017-service-state-management.md) for the full decision.

| Dimension                  | Storage                             | Written By                | Read By       |
| -------------------------- | ----------------------------------- | ------------------------- | ------------- |
| **Desired State** (config) | `system_services` table (DB)        | Admin / Web-Interface     | Controller    |
| **Actual State** (runtime) | Redis Pub/Sub (`silvasonic.status`) | Each service / Controller | Web-Interface |

---

## 3. Redis Channel Namespace

> **Status:** Planned (v0.6.0)

| Type          | Key / Channel       | Purpose                                                     |
| :------------ | :------------------ | :---------------------------------------------------------- |
| **Status**    | `silvasonic.status` | Pub/Sub: Service heartbeats. Web-Interface subscribes here. |
| **Lifecycle** | `stream:lifecycle`  | Stream: Service startup, shutdown, and crash events.        |
| **Control**   | `stream:control`    | Stream: Commands targeted at specific services.             |
| **Audit**     | `stream:audit`      | Stream: Business events (e.g., "Recording Finished").       |

---

## 4. Instance ID Convention

Services are identified by a combination of `service` (type) and `instance_id` (unique instance):

| Service Type              | `instance_id`            | Example                                     |
| ------------------------- | ------------------------ | ------------------------------------------- |
| Tier 1 Singletons         | `= service name`         | `"controller"`, `"database"`, `"processor"` |
| Recorder (multi-instance) | `= devices.name`         | `"ultramic-01"`, `"usb-mic-garden"`         |
| Uploader (multi-instance) | `= storage_remotes.slug` | `"nextcloud-main"`, `"s3-backup"`           |
| Tier 2 Singletons         | `= service name`         | `"birdnet"`, `"batdetect"`                  |

---

## 5. Payload Schemas

> **Status:** Planned (v0.6.0)

All payloads **MUST** be valid JSON and validated via Pydantic models (see [ADR-0012](../adr/0012-use-pydantic.md)).

### 5.1 Status Schema

*Channel:* `silvasonic.status` (Pub/Sub)

```json
{
  "topic": "status",
  "service": "recorder",
  "instance_id": "ultramic-01",
  "timestamp": 1706612400.123,
  "payload": {
    "health": "healthy",
    "activity": "recording",
    "meta": { "db_level": -45.2 }
  }
}
```

### 5.2 Lifecycle Schema

*Key:* `stream:lifecycle` (Stream)

```json
{
  "topic": "lifecycle",
  "event": "started",
  "service": "processor",
  "instance_id": "processor",
  "timestamp": 1706612405.0,
  "payload": { "reason": "Process initialized" }
}
```

### 5.3 Control Schema

*Key:* `stream:control` (Stream)

```json
{
  "topic": "control",
  "command": "restart_service",
  "initiator": "web-interface",
  "target_service": "recorder",
  "target_instance": "ultramic-01",
  "timestamp": 1706612500.0,
  "payload": { "force": true }
}
```

### 5.4 Audit Schema

*Key:* `stream:audit` (Stream)

```json
{
  "topic": "audit",
  "event": "recording.finished",
  "service": "recorder",
  "instance_id": "ultramic-01",
  "timestamp": 1706612600.0,
  "payload": {
    "filename": "2024-01-30_12-00-00.wav",
    "duration": 60.0
  }
}
```

---

## 6. Communication Flow Overview

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
│ INTERACTIVE PATH (Redis Pub/Sub — best-effort, v0.6.0)      │
│                                                             │
│  All Services ──[heartbeat]──► Redis ──► Web-Interface      │
│  Web-Interface ──[command]──► Redis ──► Target Service      │
└─────────────────────────────────────────────────────────────┘
```

---

## See Also

*   [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
*   [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)
*   [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
*   [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md)
*   [Filesystem Governance](filesystem_governance.md)
