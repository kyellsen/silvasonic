# silvasonic-processor

> **Status:** Implemented (since v0.6.0) · **Tier:** 1 (Infrastructure) · **Instances:** Single · **Port:** 9200
>
> 📋 **User Stories:** [processor.md](../../docs/user_stories/processor.md)

**AS-IS:** Background workhorse for data ingestion, metadata indexing, cloud synchronisation, and storage retention management. Bridges the gap between raw audio files on disk and the database. Contains the Janitor — the only component authorized to delete files from the Recorder workspace.
**Target:** Stable infrastructure component running continuously.

---

## 1. The Problem / The Gap

*   **Metadata Gap:** The Recorder writes WAV files to NVMe but has no database access (ADR-0013). Something must scan those files, extract metadata, and register them in the database so analysis workers can find them.
*   **Storage Exhaustion:** A continuously recording device will eventually fill its NVMe. Without proactive cleanup, the Recorder halts — violating Data Capture Integrity.
*   **Centralized Authority:** File deletion must be the exclusive responsibility of a single, auditable service to prevent race conditions and accidental data loss.

## 2. User Benefit

*   **Automatic Indexing:** Recordings appear in the database (and thus the Web-Interface) within seconds of being written to disk.
*   **Self-Sustaining Device:** The Janitor ensures the device can record indefinitely by cleaning up old data based on configurable thresholds.
*   **Data Safety:** Graduated retention thresholds minimize data loss while guaranteeing the Recorder never stops.

## 3. Core Responsibilities

### Inputs
*   **Filesystem:** Reads newly produced `.wav` files via polling from the Recorder workspace.
*   **Database:** Real-time system configuration updates and metadata.

### Processing
*   **Indexer:** Registers new audio files idempotently. Extracts metadata (duration, sample rate) and resolves matching raw file paths.
*   **Reconciliation Audit:** Heals split-brain states on startup (e.g., handling files blindly deleted during database outages).
*   **Upload Worker:** Intelligently batches and compresses pending recordings to lossless formats (e.g., FLAC), then transparently pushes them to configured cloud storage targets via encrypted credentials.
*   **Janitor:** Enforces retention thresholds by safely deleting files based on NVMe capacity and synchronization state.

### Outputs
*   **Database Rows:** Inserts metadata into recordings and uploads ledgers.
*   **Filesystem:** Safely purges old files from the Recorder workspace.
*   **Cloud Storage:** Uploaded compressed audio files.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                             |
| ---------------- | ------------------------------------------------------------------------ |
| **Immutable**    | Yes — config via environment variables, restart to reconfigure (ADR-0019)|
| **DB Access**    | Yes — reads/writes metadata, reads dynamic configuration                 |
| **Concurrency**  | Async Event Loop — runs continuous periodic background tasks             |
| **State**        | Stateless (runtime) but explicitly mutates the filesystem                |
| **Privileges**   | Rootless — no hardware access required (ADR-0007)                        |
| **Resources**    | Low — periodic polling and I/O, optimized file operations                |
| **QoS Priority** | `oom_score_adj=0` (Tier 1 Infrastructure Default)                        |

> [!IMPORTANT]
> The Processor is **Tier 1 (Infrastructure)** because the Janitor is critical for system survival — without it, the NVMe fills up and the Recorder halts. Despite being Tier 1, it follows the **Immutable Container** pattern like Tier 2 services (ADR-0019).

> [!WARNING]
> The Processor is the **only** service that mounts the Recorder workspace as `:rw` (for Janitor file deletion). All other consumers mount it `:ro,z` per the Consumer Principle (ADR-0009).

## 5. Configuration & Environment

### Static Environment Variables

| Variable / Mount            | Description                              | Default / Example     |
| --------------------------- | ---------------------------------------- | --------------------- |
| `SILVASONIC_PROCESSOR_PORT` | Health endpoint port                     | `9200`                |
| `SILVASONIC_LOG_DIR`        | Directory for log files                  | `/var/log/silvasonic` |
| `SILVASONIC_RECORDINGS_DIR` | Path to Recorder workspace (Read-Write)  | `/data/recorder`      |
| `SILVASONIC_PROCESSOR_DIR`  | Path to Processor workspace (Read-Write) | `/data/processor`     |

*(Note: Dynamic configuration parameters like polling rates and retention thresholds are loaded directly from the database and can be configured through the Web-Interface).*

## 6. Technology Stack

*   **Core Logic:** `silvasonic-core` service lifecycle bindings
*   **Audio Metadata:** `soundfile`
*   **Database Driver:** `sqlalchemy` (async), `asyncpg`
*   **Cloud Transfer:** `flac` (CLI encoder), `rclone` (CLI uploader)

## 7. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** analyze audio content for inferences (BirdNET / BatDetect's job).
*   **Does NOT** push or assign work to analysis workers (Workers pull tasks via central DB).

## 8. Implementation Details (Domain Specific)

### Janitor Retention Enforcement
The Janitor operates in three escalating modes based on the device's overall NVMe utilization limits (ADR-0011):

1.  **Housekeeping:** The softest tier. Removes files *only* if they have been successfully synchronized to the cloud **and** have been fully analyzed by all configured AI workers.
2.  **Defensive:** Engages as disk space grows tighter. Removes files once they are successfully synchronized to the cloud. Local analysis success is ignored to prioritize keeping the Recorder alive.
3.  **Panic:** The ultimate failsafe. Removes the oldest files regardless of synchronization or analysis state. Engages when the disk is perilously close to full or when the database connection is offline and blind filesystem operations are required.

When a file is purged by the Janitor, it performs a **Soft Delete** purely on the database side: the file is explicitly unlinked from disk, but its metadata row is preserved with a deletion flag for historical auditing. Deletions are processed in configurable, throttled batches to prevent disk thrashing.

### Split-Brain Healing
Because the **Panic** mode may blindly unlink files when the database is temporarily unreachable, the Processor always starts with a Reconciliation Audit. This compares the actual files on disk against the database ledger and heals any discrepancies (orphaned rows) before beginning standard polling operations.

## 9. References

*   [ADR-0009: Zero-Trust Data Sharing](../../docs/adr/0009-zero-trust-data-sharing.md) — Consumer Principle
*   [ADR-0011: Audio Recording Strategy](../../docs/adr/0011-audio-recording-strategy.md) — Disk Retention Tiers
*   [ADR-0018: Worker Pull Orchestration](../../docs/adr/0018-worker-pull-orchestration.md) — Worker Self-Service
*   [User Stories — Processor](../../docs/user_stories/processor.md)
