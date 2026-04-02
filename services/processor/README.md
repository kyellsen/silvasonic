# Processor Service

> **Status:** implemented (v0.5.0)
>
> **Tier:** 1 (Infrastructure) · **Port:** 9200

Background workhorse for data ingestion, metadata indexing, and storage retention management. Bridges the gap between raw audio files on disk and the database. Contains the Janitor — the only component authorized to delete files from the Recorder workspace.
Immutable Container pattern (ADR-0019): reads config from `system_config` on startup, restart to reconfigure.

---

## 1. The Problem / The Gap

*   **Metadata Gap:** The Recorder writes WAV files to NVMe but has no database access (ADR-0013). Something must scan those files, extract metadata, and register them in the `recordings` table so analysis workers can find them.
*   **Storage Exhaustion:** A continuously recording device will eventually fill its NVMe. Without proactive cleanup, the Recorder halts — violating Data Capture Integrity.
*   **Centralized Authority:** File deletion must be the exclusive responsibility of a single, auditable service to prevent race conditions and accidental data loss.

## 2. User Benefit

*   **Automatic Indexing:** Recordings appear in the database (and thus the Web-Interface) within seconds of being written to disk.
*   **Self-Sustaining Device:** The Janitor ensures the device can record indefinitely by cleaning up old data based on configurable thresholds.
*   **Data Safety:** Graduated retention thresholds (Housekeeping → Defensive → Panic) minimize data loss while guaranteeing the Recorder never stops.

## 3. Features & Core Responsibilities

### Indexer (`indexer.py`)

*   **Filesystem Polling:** Periodic filesystem polling of `recorder/*/data/processed/*.wav`.
*   **Registration:** Extracts WAV metadata via `soundfile` (duration, sample_rate, channels, size) and registers recordings in the `recordings` table (idempotent, no duplicates). Resolves matching raw file path for each processed segment.

### Reconciliation Audit (`reconciliation.py`)

*   Runs once on startup before the Indexer polling loop begins.
*   Heals Split-Brain state caused by Panic Mode blind deletion during DB outages.
*   Marks orphaned `recordings` rows (`local_deleted = false` but file missing) as `local_deleted = true`.

### Janitor (`janitor.py`)

The **only** service authorized to delete files from the Recorder workspace (ADR-0009). Operates in three escalating modes based on NVMe utilization (ADR-0011 §6):

| Mode             | Threshold | Criteria                                                      | Log Level  |
| ---------------- | --------- | ------------------------------------------------------------- | ---------- |
| **Housekeeping** | > 70%     | `uploaded=true` AND `analysis_state` complete for all workers | `INFO`     |
| **Defensive**    | > 80%     | `uploaded=true` (regardless of analysis)                      | `WARNING`  |
| **Panic**        | > 90%     | **Oldest** files regardless of status                         | `CRITICAL` |

*   **Soft Delete:** Files explicitly removed, DB row preserved `local_deleted=TRUE`.
*   **Batch Size:** Deletions limited to `janitor_batch_size` (default: 50) per cycle.
*   **Cloud-Sync-Fallback:** Skips `uploaded` condition if no remote target is configured.
*   **Panic Fallback:** Uses filesystem `mtime` for blind cleanup when DB is offline.

### Service Lifecycle (`__main__.py`)

*   `ProcessorService(SilvaService)` with health, heartbeat, graceful shutdown.
*   Runtime config loading from `system_config` table (`ProcessorSettings`).
*   Reports indexer and janitor metrics in heartbeat payload.
*   Compose integration as Tier 1 service (depends on DB + Redis + Controller).

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

> [!WARNING]
> The Processor is the **only** service that mounts the Recorder workspace as `:rw` (for Janitor file deletion). All other consumers (BirdNET, BatDetect) mount it `:ro,z` per the Consumer Principle (ADR-0009).

## 5. Configuration

### Static Environment Variables

Configured via `settings.py` using `pydantic-settings`.

| Environment Variable        | Default               | Description                              |
| :-------------------------- | :-------------------- | :--------------------------------------- |
| `SILVASONIC_PROCESSOR_PORT` | `9200`                | Health endpoint port                     |
| `SILVASONIC_LOG_DIR`        | `/var/log/silvasonic` | Directory for log files                  |
| `SILVASONIC_RECORDINGS_DIR` | `/data/recorder`      | Path to Recorder workspace (Read-Only)   |
| `SILVASONIC_PROCESSOR_DIR`  | `/data/processor`     | Path to Processor workspace (Read-Write) |

### Dynamic Configuration (Database)

Runtime settings are stored in `system_config` (key: `processor`) and seeded from `config/defaults.yml` by the Controller.

| Setting                       | Default | Description                    |
| :---------------------------- | :------ | :----------------------------- |
| `janitor_threshold_warning`   | `70.0`  | Housekeeping Trigger (%)       |
| `janitor_threshold_critical`  | `80.0`  | Defensive Trigger (%)          |
| `janitor_threshold_emergency` | `90.0`  | Panic Trigger (%)              |
| `janitor_interval_seconds`    | `60`    | Seconds between cleanup cycles |
| `janitor_batch_size`          | `50`    | Max files deleted per cycle    |
| `indexer_poll_interval`       | `2.0`   | Seconds between indexing scans |

*Changes via Web-UI require a container restart to take effect (ADR-0019).*

## 6. Technology Stack & Modules

*   **Modules:**
    - `__main__.py` (82 lines) — Service entry point, lifecycle, config.
    - `indexer.py` (71 lines) — Filesystem polling, WAV registration.
    - `janitor.py` (122 lines) — Disk monitoring, retention enforcement.
    - `reconciliation.py` (20 lines) — Split-Brain healing on startup.
    - `settings.py` (8 lines) — Environment variable bindings.
*   **Libraries:** `sqlalchemy`, `asyncpg`, `soundfile`, `structlog`

## 7. Tests

*   **Unit:** 100% coverage on indexer, reconciliation, settings; 89% on janitor.
*   **Integration:** Testcontainer-based tests for indexer, janitor, reconciliation, lifecycle.
*   **System:** Full Podman lifecycle tests including resilience scenarios.
*   **Smoke:** Health endpoint and heartbeat validation.

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** analyze audio content (BirdNET / BatDetect's job).
*   **Does NOT** upload files to the cloud (Processor Cloud-Sync-Worker does this internally).
*   **Does NOT** assign work to analysis workers (Workers self-serve via DB polling).

## 9. References

*   [Database Schema (DDL)](../../services/database/init/01-init-schema.sql)
*   [ADR-0009](../../docs/adr/0009-zero-trust-data-sharing.md) — Zero-Trust Data Sharing
*   [ADR-0011](../../docs/adr/0011-audio-recording-strategy.md) — Audio Recording Strategy
*   [ADR-0018](../../docs/adr/0018-worker-pull-orchestration.md) — Worker Pull Orchestration
*   [Milestone v0.5.0](../../docs/development/milestone_0_5_0.md) — Implementation plan
