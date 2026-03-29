# Uploader

> **Status:** planned - Not implemented · **Tier:** 2 · **Instances:** Multi-instance: one per remote storage target

**TO-BE:** Data exfiltration service responsible for compressing Raw recordings to FLAC and synchronizing them to remote storage providers. Ensures the field device never depends on network connectivity — recordings are safely stored locally first (Store & Forward).

---

## 1. The Problem / The Gap

*   **No Off-Device Backup:** Without an Uploader, all recordings exist only on the local NVMe. Hardware failure, theft, or SD card corruption means permanent data loss.
*   **Storage Limits:** Even with the Janitor managing retention, local NVMe capacity is finite. Exfiltrating data to the cloud frees local space for continued recording.

## 2. User Benefit

*   **Data Safety:** Recordings are automatically archived to remote storage (Nextcloud, S3, SFTP).
*   **Indefinite Recording:** Once uploaded, the Janitor can safely delete local copies, enabling continuous operation for months or years.
*   **Multi-Target:** Different storage providers for different purposes (e.g., Nextcloud for sharing, S3 for long-term archive).

## 3. Core Responsibilities

### Inputs

*   **Database (Polling):** Reads `recordings` table for files where `uploaded=false` and `local_deleted=false`.
*   **Filesystem (Read-Only):** Reads Raw WAV files from the Recorder workspace.
*   **Database (Config):** Reads `storage_remotes` table for connection parameters (endpoint, credentials, path).

### Processing

*   **FLAC Compression:** Converts Raw WAV to FLAC for bandwidth-efficient upload (lossless, ~50% size reduction).
*   **Upload:** Transfers FLAC files to the configured remote storage provider.
*   **Audit Logging:** Records upload attempts in the `uploads` table (immutable audit log).

### Outputs

*   **FLAC Files** uploaded to remote storage.
*   **Database Rows:** INSERTs into `uploads` table (success/failure, file size, errors).
*   **Database Updates:** Sets `uploaded=true` on `recordings` row after confirmed upload.
*   **Redis Heartbeats:** Via `SilvaService` base class (ADR-0019).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                  |
| ---------------- | ------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup, restart to reconfigure (ADR-0019)    |
| **DB Access**    | Yes — reads `recordings`, `storage_remotes`; writes `uploads` |
| **Concurrency**  | Async event loop, sequential uploads per instance             |
| **State**        | Stateless (runtime) — upload progress not persisted           |
| **Privileges**   | Rootless (ADR-0007)                                           |
| **Resources**    | Medium — FLAC encoding is CPU-intensive for large files       |
| **QoS Priority** | `oom_score_adj=250` — Low Priority, below recording priority (ADR-0020) |

> [!NOTE]
> Each Uploader instance is managed by the Controller as a Tier 2 container. The Controller creates one Uploader per `storage_remotes` entry (similar to one Recorder per Device).

## 5. Configuration & Environment

### Static Configuration (Environment Variables & Mounts)

| Variable / Mount                       | Description                                      | Default / Example            |
| -------------------------------------- | ------------------------------------------------ | ---------------------------- |
| Health port                            | Internal health endpoint                         | `9500`                       |
| `SILVASONIC_STORAGE_REMOTE_SLUG`       | Identifier for the storage target (DB lookup key)| `nextcloud-main`             |
| `SILVASONIC_REDIS_URL`                 | Redis connection URL                             | `redis://redis:6379/0`       |
| `SILVASONIC_INSTANCE_ID`               | Instance identifier for heartbeats               | `nextcloud-main`             |
| `POSTGRES_HOST`, `POSTGRES_PORT`, etc. | DB connection (reads `storage_remotes`, `recordings`, `system_config`) | (from Controller injection) |
| Recorder workspace `:ro`               | Recorder workspace (read-only, Consumer Principle, ADR-0009)          | (bind mount)                |

> [!NOTE]
> Remote type, endpoint, and credentials are stored in the `storage_remotes.config` JSONB column and read from the database on startup — not via environment variables. The Uploader generates a temporary `rclone.conf` at runtime from this data (see Milestone v0.6.0 Phase 4).

### Dynamic Configuration (Database)

Runtime-tunable settings stored in the `system_config` table under key `uploader_settings`. As an **Immutable Container** (ADR-0019), the Uploader reads these settings *once* on startup.

| Setting               | Description                          | Default / Example |
| --------------------- | ------------------------------------ | ----------------- |
| `enabled`             | Global toggle for upload activity    | `true`            |
| `poll_interval`       | Seconds between checking DB for work | `30`              |
| `bandwidth_limit`     | Rclone `--bwlimit` parameter String  | `"1M"`            |
| `schedule_start_hour` | Opt-in: hour to start daily upload window  | `null` (24/7)     |
| `schedule_end_hour`   | Opt-in: hour to end daily upload window    | `null` (24/7)     |

**Update Mechanism (State Reconciliation):**
1. User changes settings in Web UI.
2. Frontend updates `system_config` in DB and publishes a `silvasonic:nudge` event to the Controller (per ADR-0017).
3. The Controller restarts the Uploader container(s).
4. The Uploader reads the new `UploaderSettings` from the database upon startup.

## 6. Technology Stack

*   **Base Image:** `python:3.11-slim-bookworm` (with rclone installed)
*   **FLAC Encoding:** `ffmpeg` (via Python `subprocess`). Highly optimized, stable for large files, and streams data without blowing up container memory.
*   **Upload Protocols:** `rclone` (system binary via Python wrapper). Serves as a universal backend for WebDAV, S3, SFTP, and dozens of other protocols without needing protocol-specific Python libraries.
*   **Database:** `sqlalchemy` (2.0+ async), `asyncpg`

## 7. Open Questions & Future Ideas

*   Parallel uploads: Multiple files concurrently for faster throughput.
*   Resume support: Track partial uploads to avoid re-uploading on interruption.
*   Bandwidth throttling: Avoid saturating the network link during peak hours.

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** delete local files (Janitor's job in Processor).
*   **Does NOT** analyze audio (BirdNET / BatDetect's job).
*   **Does NOT** manage its own lifecycle (Controller starts/stops Uploader instances).

## 9. References

*   [Database Schema (DDL)](../../services/database/init/01-init-schema.sql) — authoritative definition of `uploads` and `storage_remotes` tables
*   [ADR-0011](../adr/0011-audio-recording-strategy.md) — Raw → FLAC for cloud, Retention Policy
*   [ADR-0013](../adr/0013-tier2-container-management.md) — Tier 2 lifecycle management
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService
*   [ADR-0023](../adr/0023-configuration-management.md) — Configuration Management (upload settings)
*   [Glossary: Uploader, Store & Forward, Raw Artifact, Storage Remote](../glossary.md)
*   [ROADMAP.md](../../ROADMAP.md) — milestone (v0.6.0)
