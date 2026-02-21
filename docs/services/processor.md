# Processor Service

> **Status:** Planned (v0.5.0) · **Tier:** 1 · **Instances:** Single · **Port:** 9200

Background workhorse for data ingestion, metadata indexing, and storage retention management. Bridges the gap between raw audio files on disk and the database. Contains the Janitor — the only component authorized to delete files from the Recorder workspace.

---

## 1. The Problem / The Gap

*   **Metadata Gap:** The Recorder writes WAV files to NVMe but has no database access (ADR-0013). Something must scan those files, extract metadata, and register them in the `recordings` table so analysis workers can find them.
*   **Storage Exhaustion:** A continuously recording device will eventually fill its NVMe. Without proactive cleanup, the Recorder halts — violating Data Capture Integrity.
*   **Centralized Authority:** File deletion must be the exclusive responsibility of a single, auditable service to prevent race conditions and accidental data loss.

## 2. User Benefit

*   **Automatic Indexing:** Recordings appear in the database (and thus the Web-Interface) within seconds of being written to disk — no manual import step.
*   **Self-Sustaining Device:** The Janitor ensures the device can record indefinitely by cleaning up old data based on configurable thresholds.
*   **Data Safety:** Graduated retention thresholds (Housekeeping → Defensive → Panic) minimize data loss while guaranteeing the Recorder never stops.

## 3. Core Responsibilities

### Inputs

*   **Filesystem (Polling):** Watches the Recorder workspace (`/mnt/data/recordings`) for new `.wav` files via periodic filesystem polling (Filesystem Polling pattern, see Glossary).
*   **Database (State):** Reads `recordings` table to determine upload and analysis status for Janitor decisions.
*   **Disk Usage:** Monitors NVMe utilization to trigger retention thresholds.

### Processing

#### Indexer (Librarian)

*   Extracts metadata from new WAV files (duration, sample rate, channels, file size).
*   Registers files in the `recordings` database table.
*   Idempotent — checks for existing entries to prevent duplicates.

#### Janitor (Retention)

The **only** service authorized to delete files from the Recorder workspace (ADR-0009). Operates in three escalating modes based on NVMe utilization (ADR-0011 §6):

| Mode             | Threshold | Criteria                                                      | Log Level  |
| ---------------- | --------- | ------------------------------------------------------------- | ---------- |
| **Housekeeping** | > 70%     | `uploaded=true` AND `analysis_state` complete for all workers | `INFO`     |
| **Defensive**    | > 80%     | `uploaded=true` (regardless of analysis)                      | `WARNING`  |
| **Panic**        | > 90%     | **Oldest** files regardless of status                         | `CRITICAL` |

*   **Soft Delete:** Files are physically removed, but the database row is preserved with `local_deleted=TRUE` to maintain the historical inventory.
*   **Fallback:** In Panic Mode, if the database is offline, falls back to filesystem `mtime` for blind cleanup.

### Outputs

*   **Database Rows:** INSERTs into `recordings` table (Indexer) and UPDATEs `local_deleted` flag (Janitor).
*   **Redis Events:** Publishes notifications on new recordings and deletion events (best-effort, fire-and-forget).
*   **Redis Heartbeats:** Via `SilvaService` base class (ADR-0019).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                             |
| ---------------- | ------------------------------------------------------------------------ |
| **Immutable**    | Yes — config at startup, restart to reconfigure (ADR-0019)               |
| **DB Access**    | Yes — reads/writes `recordings`, reads `system_config`                   |
| **Concurrency**  | Async event loop (`asyncio`) — Indexer and Janitor run as periodic tasks |
| **State**        | Stateless (runtime), but manages critical file operations                |
| **Privileges**   | Rootless — no hardware access required (ADR-0007)                        |
| **Resources**    | Low — periodic polling and I/O, minimal CPU                              |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure                      |

> [!IMPORTANT]
> The Processor is **Tier 1 (Infrastructure)** because the Janitor is critical for system survival — without it, the NVMe fills up and the Recorder halts. Despite being Tier 1, it follows the **Immutable Container** pattern like Tier 2 services (ADR-0019).

## 5. Configuration & Environment

| Variable / Mount                         | Description                                        | Default / Example |
| ---------------------------------------- | -------------------------------------------------- | ----------------- |
| `SILVASONIC_PROCESSOR_PORT`              | Health endpoint port                               | `9200`            |
| `SILVASONIC_JANITOR_THRESHOLD_WARNING`   | Housekeeping trigger (%)                           | `70.0`            |
| `SILVASONIC_JANITOR_THRESHOLD_CRITICAL`  | Defensive trigger (%)                              | `80.0`            |
| `SILVASONIC_JANITOR_THRESHOLD_EMERGENCY` | Panic trigger (%)                                  | `90.0`            |
| `SILVASONIC_JANITOR_INTERVAL_SECONDS`    | Seconds between cleanup cycles                     | `60`              |
| `SILVASONIC_INDEXER_POLL_INTERVAL`       | Seconds between indexing scans                     | `5.0`             |
| `/mnt/data/recordings:rw`                | Recorder workspace (read-write for Janitor delete) | —                 |
| `POSTGRES_HOST`, `SILVASONIC_DB_*`       | Database connection                                | via `.env`        |

> [!WARNING]
> The Processor is the **only** service that mounts the Recorder workspace as `:rw` (for Janitor file deletion). All other consumers (BirdNET, BatDetect, Uploader) mount it `:ro` per the Consumer Principle (ADR-0009).

## 6. Technology Stack

*   **Python:** `silvasonic-core` (SilvaService, database models, health monitoring)
*   **Database:** `sqlalchemy` (2.0+ async), `asyncpg`
*   **Filesystem:** `pathlib`, `soundfile` (WAV metadata extraction)

## 7. Open Questions & Future Ideas

*   WAV metadata extraction: `soundfile` vs. `ffprobe` — trade-off between dependency weight and robustness
*   Notification optimization: Redis `PUBLISH` when new recordings are indexed, so workers react instantly instead of polling
*   Continuous aggregates: Processor could trigger TimescaleDB materialized views for pre-computed statistics
*   Archive-before-delete: Copy files to a staging area before Janitor deletion for extra safety

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** analyze audio content (BirdNET / BatDetect's job — ADR-0018 Worker Pull).
*   **Does NOT** upload files to the cloud (Uploader's job).
*   **Does NOT** provide a UI (Web-Interface's job).
*   **Does NOT** assign work to analysis workers (Workers self-serve via DB polling — ADR-0018).
*   **Does NOT** compress audio for upload (Uploader handles FLAC conversion — ADR-0011).

## 9. References

*   [ADR-0009](../adr/0009-zero-trust-data-sharing.md) — Consumer Principle, Janitor delete authority
*   [ADR-0011](../adr/0011-audio-recording-strategy.md) — Audio Recording Strategy, Retention Policy (§6)
*   [ADR-0018](../adr/0018-worker-pull-orchestration.md) — Worker Pull Orchestration, Processor role
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService lifecycle
*   [Port Allocation](../arch/port_allocation.md) — Processor on port 9200
*   [Glossary: Processor, Janitor, Data Retention Policy](../glossary.md)
*   [VISION.md](../../VISION.md) — roadmap entry (v0.5.0)
