# Messaging Patterns & Protocols

This document defines the synchronous (Polling) and asynchronous (Pub/Sub) communication standards within Silvasonic.

---

## 1. Architectural Decision: Polling vs. Event-Driven (ADR)

To satisfy the **"Data Capture Integrity"** directive (Section 3 in AGENTS.md), the system employs a **Hybrid Architecture** that strictly delineates where "Polling" (Pull) and "Pub/Sub" (Push) patterns are used.

### 1.1. The Critical Path (Polling/Pull)
**Philosophy**: The Filesystem and Database are the "Source of Truth". If a service misses a transient Pub/Sub message (e.g., during a restart), data must not be lost.
*   **Recorder -> Processor**: **Filesystem Polling**.
    *   *Why?* The Recorder must never block or crash due to a Redis failure. Writing to NVMe is the most reliable operation.
    *   *Mechanism*: The Processor periodically scans the `recordings/` directory (or uses `inotify` as an optimization, but *must* fall back to scanning).
    *   *Robustness*: If Processor is down for 1 hour, it simply resumes scanning where it left off, finding all 1 hour of recordings.
*   **Processor -> Workers (BirdNET/Uploader/Janitor)**: **Database Polling**.
    *   *Why?* Rate limiting and Atomic Claims.
    *   *Mechanism*: Workers use `SELECT ... FOR UPDATE SKIP LOCKED` (or simple state flags) to claim jobs.
    *   *Robustness*: Prevents race conditions where two Analyzers grab the same file. Implicitly handles backpressure (if DB is slow, workers just wait).

### 1.2. The Interactive Path (Pub/Sub)
**Philosophy**: Responsiveness for the User Interface. Events are "Notifications", not "Work Orders".
*   **Processor -> UI (Status)**: **Redis Pub/Sub**.
    *   *Channel*: `silvasonic.audit` or `silvasonic.status`
    *   *Use Case*: "New file indexed!" -> UI updates the timeline immediately without waiting for a refresh interval.
    *   *Failure Mode*: If the UI misses the message, the user just sees the data 5 seconds later (via standard polling). **Acceptable**.
*   **Control/Maintenance**: **Redis Pub/Sub**.
    *   *Channel*: `silvasonic.control`
    *   *Use Case*: "Restart BirdNET" or "Re-read Config".

### 1.3 Summary Table
| Interaction | Pattern | Source of Truth |
| :--- | :--- | :--- |
| **Recorder Write** | IO Stream | NVMe (`file_raw`) |
| **Indexing** | FS Polling | Filesystem structure |
| **Analysis Job** | DB Polling | `recordings` table (`analysis_state` JSON check) |
| **Upload Job** | DB Polling | `recordings` table (`uploaded=false`) |
| **UI Updates** | Pub/Sub | Redis Channel (Optimization) |

---

## 2. Redis Channel Namespace

All events use the prefix `silvasonic`.

| Channel | Pattern | Purpose | Payload Schema |
| :--- | :--- | :--- | :--- |
| **Status** | `silvasonic.status` | **Firehose** of all service heartbeats. UI listens here. | [Status Schema](#31-status-schema) |
| **Lifecycle** | `silvasonic.lifecycle` | Service startup, shutdown, and error events. | [Lifecycle Schema](#32-lifecycle-schema) |
| **Control** | `silvasonic.control` | Commands targeted at specific services (e.g., "Reload Config"). | [Control Schema](#33-control-schema) |
| **Audit** | `silvasonic.audit` | High-level business events (e.g., "Recording Finished", "Upload Success"). | [Audit Schema](#34-audit-schema) |

## 3. Payload Schemas

All payloads **MUST** be valid JSON.
All timestamps **MUST** be Unix Floats (UTC).

### 3.1 Status Schema
*Channel:* `silvasonic.status`
*Also stored as Redis Key:* `status:{service}:{instance_id}` (TTL: 10s/10m)

Services **MUST** report their state using the "Traffic Light" pattern.

```json
{
  "topic": "status",
  "service": "recorder",
  "instance_id": "front",
  "timestamp": 1706612400.123,
  "payload": {
      "health": "healthy",       // healthy | degraded
      "activity": "recording",   // idle | recording | uploading | analyzing
      "progress": null,          // 0-100 or null
      "message": "Audio stream active (48kHz)",
      "meta": {                  // Service-specific metrics
          "db_level": -45.2,
          "disk_free_gb": 120
      }
  }
}
```

> [!IMPORTANT]
> **Green (`healthy`)**: Functioning normally.
> **Yellow (`degraded`)**: Online but with issues (Disk full warning, Sensor unreachable).
> **Red (Offline)**: Inferred by **absence** of record (TTL Expired).

### 3.2 Lifecycle Schema
*Channel:* `silvasonic.lifecycle`

Emitted on startup, clean shutdown, or unhandled exceptions.

```json
{
  "topic": "lifecycle",
  "event": "started", // started | stopping | crashed
  "service": "uploader",
  "instance_id": "main",
  "timestamp": 1706612405.000,
  "payload": {
      "version": "0.1.0",
      "pid": 1234,
      "reason": "Process initialized" 
  }
}
```

### 3.3 Control Schema
*Channel:* `silvasonic.control`

Targeted commands. Services MUST filter by `target_service` and `target_instance`.

```json
{
  "topic": "control",
  "command": "reload_config", // reload_config | restart | trigger_maintenance
  "initiator": "web-interface",
  "target_service": "birdnet",
  "target_instance": "*", // "*" means all instances
  "timestamp": 1706612500.000,
  "payload": {
      "params": { "min_confidence": 0.7 }
  }
}
```

### 3.4 Audit Schema
*Channel:* `silvasonic.audit`

Business-level events for the "Activity Log".

```json
{
  "topic": "audit",
  "event": "recording.finished",
  "service": "recorder",
  "instance_id": "front",
  "timestamp": 1706612600.000,
  "payload": {
     "filename": "2024-01-30_12-00-00.wav",
     "duration": 60.0
  }
}
```

## 4. DB Polling Patterns (Implementation)

### 4.1 Filename-to-Time Cursor

Since the `processor` indexes files into the database but workers might track progress via filenames, the system translates filename-timestamps to DB Queries.

**Pattern Steps:**
1. **Filename Parsing**: Extract the timestamp (`YYYY-MM-DD_HH-MM-SS`).
2. **Time Normalization**: Convert to UTC datetime.
3. **Database Query**: `SELECT COUNT(*) FROM recordings WHERE time > :dt`

### 4.2 Status Labeling (Lag)

| Lag (n files) | Status | UI Color |
| :--- | :--- | :--- |
| $n \le 2$ | `ok` | Green / "Synced" |
| $2 < n \le 10$ | `pending` | Blue / "Pending" |
| $n > 10$ | `lagging` | Amber / "Lagging" |
