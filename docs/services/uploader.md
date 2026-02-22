# Uploader

> **Status:** Planned (v0.6.0) · **Tier:** 2 · **Instances:** Multi-instance: one per remote storage target

Data exfiltration service responsible for compressing Raw recordings to FLAC and synchronizing them to remote storage providers. Ensures the field device never depends on network connectivity — recordings are safely stored locally first (Store & Forward).

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
| **QoS Priority** | `oom_score_adj=200` — expendable, below recording priority    |

> [!NOTE]
> Each Uploader instance is managed by the Controller as a Tier 2 container. The Controller creates one Uploader per `storage_remotes` entry (similar to one Recorder per Device).

## 5. Configuration & Environment

| Variable / Mount          | Description                       | Default / Example                                                |
| ------------------------- | --------------------------------- | ---------------------------------------------------------------- |
| Health port               | Internal health endpoint          | `9500`                                                           |
| `/mnt/data/recordings:ro` | Recorder workspace (read-only)    | Consumer Principle                                               |
| `STORAGE_REMOTE_SLUG`     | Identifier for the storage target | `nextcloud-main`                                                 |
| `STORAGE_REMOTE_TYPE`     | Protocol (s3, webdav, sftp)       | `webdav`                                                         |
| `STORAGE_REMOTE_ENDPOINT` | Remote URL                        | `https://cloud.example.com/remote.php/dav/files/user/silvasonic` |

## 6. Technology Stack

*   **FLAC Encoding:** `soundfile` or `ffmpeg` (subprocess)
*   **Upload Protocols:** `boto3` (S3), `webdavfs` (WebDAV/Nextcloud), `paramiko` (SFTP)
*   **Database:** `sqlalchemy` (2.0+ async), `asyncpg`

## 7. Open Questions & Future Ideas

*   Parallel uploads: Multiple files concurrently for faster throughput.
*   Resume support: Track partial uploads to avoid re-uploading on interruption.
*   Bandwidth throttling: Avoid saturating the network link during peak hours.
*   Rclone integration: Use rclone as a universal backend instead of protocol-specific libraries.

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** delete local files (Janitor's job in Processor).
*   **Does NOT** analyze audio (BirdNET / BatDetect's job).
*   **Does NOT** manage its own lifecycle (Controller starts/stops Uploader instances).

## 9. References

*   [ADR-0011](../adr/0011-audio-recording-strategy.md) — Raw → FLAC for cloud, Retention Policy
*   [ADR-0013](../adr/0013-tier2-container-management.md) — Tier 2 lifecycle management
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService
*   [Glossary: Uploader, Store & Forward, Raw Artifact, Storage Remote](../glossary.md)
*   [VISION.md](../../VISION.md) — roadmap entry (v0.6.0)
