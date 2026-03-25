# Milestone v0.5.0 — Analysis & Backend Orchestration

> **Target:** v0.5.0 — Processor Service (Indexer + Janitor), `recordings` Schema & Indices, Processor Config Seeding, Controller Integration
>
> **Status:** 🔨 In Progress
>
> **References:** [ADR-0009](../adr/0009-zero-trust-data-sharing.md), [ADR-0011](../adr/0011-audio-recording-strategy.md), [ADR-0018](../adr/0018-worker-pull-orchestration.md), [ADR-0019](../adr/0019-unified-service-infrastructure.md), [ADR-0023](../adr/0023-configuration-management.md), [ADR-0025](../adr/0025-recordings-standard-table.md), [Processor Service Spec](../services/processor.md), [Service Blueprint](service_blueprint.md)
>
> **User Stories:** [US-P01](../user_stories/processor.md#us-p01), [US-P02](../user_stories/processor.md#us-p02), [US-P03](../user_stories/processor.md#us-p03), [US-P04](../user_stories/processor.md#us-p04)

---

## Phase 1: Processor Service Skeleton & Compose Integration

**Goal:** Create the Processor service following the Service Blueprint, integrate into Compose as a Tier 1 service, and verify basic lifecycle (health, heartbeat, graceful shutdown).

**User Stories:** —

### Tasks

- [ ] Scaffold `services/processor/` following the Service Blueprint (§1):
  - `Containerfile`, `pyproject.toml`, `README.md`
  - `src/silvasonic/processor/__init__.py`, `__main__.py`, `py.typed`
  - `tests/unit/`, `tests/integration/`
- [ ] Implement `ProcessorService(SilvaService)` in `__main__.py`:
  - `service_name = "processor"`, `service_port = 9200`
  - Override `run()` with placeholder logic (Phase 3+4 fill this in)
  - Read `ProcessorSettings` from `system_config` table on startup (single DB read, Immutable Container pattern, ADR-0019)
- [ ] Register in workspace:
  - Root `pyproject.toml`: add `silvasonic-processor` to `[project] dependencies` and `[tool.uv.sources]`
- [ ] Add `Containerfile` following the Service Blueprint (§5):
  - Base: `python:3.11-slim-bookworm`
  - System deps: `curl`, `libsndfile1` (WAV metadata via `soundfile`)
  - Port: `9200`
- [ ] Add Processor to `compose.yml` as Tier 1 service:
  - `container_name: silvasonic-processor`
  - Depends on `database` (healthy)
  - Mount Recorder workspace **read-write** (`${SILVASONIC_WORKSPACE_PATH}/recorder:/data/recorder:z`) — Processor is the **only** non-Recorder service with `:rw` access (Janitor delete authority, ADR-0009)
  - Mount Processor workspace read-write (`${SILVASONIC_WORKSPACE_PATH}/processor:/data/processor:z`)
  - Redis URL, DB env vars
  - Healthcheck on `:9200/healthy`
- [ ] Add `compose.override.yml` dev mounts for hot-reload
- [ ] Add `SILVASONIC_PROCESSOR_PORT=9200` to `.env.example`
- [ ] Unit tests: package import, lifecycle (start/shutdown), settings loading
- [ ] Integration test: Processor starts in Testcontainer with DB, reports healthy
- [ ] `just check` passes

---

## Phase 2: Database Schema Enhancements

**Goal:** Finalize the `recordings` table schema and add indices for Worker Pull (ADR-0018) and Upload polling (v0.6.0 prep) — before the Indexer writes to this table.

**User Stories:** —

> **Decision (ADR-0025):** `recordings` remains a **standard PostgreSQL table** (no Hypertable). FK constraints from `detections` and `uploads` are preserved. Data volume (~2M rows/year) does not require partitioning. See [ADR-0025](../adr/0025-recordings-standard-table.md).

### Tasks

- [ ] Add partial index for Worker Pull pattern (ADR-0018):
  ```sql
  CREATE INDEX ix_recordings_analysis_pending
  ON recordings (time ASC)
  WHERE local_deleted = false;
  ```
- [ ] Add partial index for Upload polling (v0.6.0 preparation):
  ```sql
  CREATE INDEX ix_recordings_upload_pending
  ON recordings (time ASC)
  WHERE uploaded = false AND local_deleted = false;
  ```
- [ ] Verify `analysis_state` JSONB column supports the Worker Pull `SELECT ... FOR UPDATE SKIP LOCKED` pattern efficiently
- [ ] Update `services/database/init/01-init-schema.sql` with new indices
- [ ] Update SQLAlchemy ORM models in `silvasonic.core.database.models` if schema changes apply
- [ ] Integration test: verify Worker Pull query pattern (`FOR UPDATE SKIP LOCKED`) works correctly against real DB

---

## Phase 3: Indexer — Filesystem Polling & Recording Registration

**Goal:** The Indexer scans the Recorder workspace for promoted WAV files, extracts metadata, and registers them in the `recordings` table. Recordings appear in the database within seconds of being written to disk.

**User Stories:** US-P01 (Aufnahmen erscheinen automatisch)

### Tasks

- [ ] Implement `silvasonic/processor/indexer.py` — `Indexer` class:
  - Periodic filesystem polling of all `recorder/*/data/processed/*.wav` (configurable interval from `ProcessorSettings.indexer_poll_interval`, default: `2.0` seconds)
  - Extract WAV metadata via `soundfile`: duration, sample_rate, channels, file size
  - Determine `sensor_id` from directory structure (`recorder/{device_name}/data/...`)
  - Locate corresponding raw file: `recorder/{device_name}/data/raw/{same_filename}.wav`
  - Calculate `filesize_raw` from the raw file
- [ ] Register each new WAV in the `recordings` table:
  - `time`: parsed from segment filename (ISO timestamp)
  - `sensor_id`: device name from directory path
  - `file_raw`, `file_processed`: relative paths to both streams
  - `duration`, `sample_rate`, `filesize_raw`, `filesize_processed`
  - `uploaded = false`, `local_deleted = false`
  - `analysis_state = '{}'::jsonb` (empty — no workers have processed it yet)
  - Idempotent: check for existing entry by `file_processed` before insert (avoid duplicates)
- [ ] Only index files from `data/` directories — never from `.buffer/` (only complete, promoted segments)
- [ ] Integrate Indexer as periodic async task in `ProcessorService.run()`
- [ ] Report indexing metrics via `get_extra_meta()` for heartbeat:
  - `last_indexed_at`, `pending_count` (files on disk not yet in DB), `total_indexed`
- [ ] Update health component: `self.health.update_status("indexer", True/False, details)`
- [ ] Implement **Filesystem Reconciliation Audit** (Split-Brain Healing):
  - Runs once on Processor startup, before the Indexer polling loop begins
  - Queries all `recordings` rows where `local_deleted = false`
  - Verifies `file_processed` exists on the filesystem
  - If file is missing: sets `local_deleted = true` and logs at `WARNING` level with reason `"reconciliation"`
  - Reports `reconciled_count` in startup log and heartbeat metrics
  - Rationale: Heals Split-Brain state caused by Panic-Mode blind deletion (Phase 4) during DB outages
- [ ] Unit tests: WAV metadata extraction, path parsing, idempotent insert logic, `.buffer/` exclusion, reconciliation audit logic
- [ ] Integration test: place WAV files in mock workspace → Indexer picks them up → verify `recordings` rows
- [ ] Integration test: recordings in DB with missing files on disk → Reconciliation Audit marks them `local_deleted = true`

---

## Phase 4: Janitor — Data Retention & Storage Management

**Goal:** The Janitor monitors NVMe disk utilization and enforces the escalating retention policy (ADR-0011 §6) to prevent storage exhaustion. The Recorder never stops due to a full disk.

**User Stories:** US-P02 (Endlos-Aufnahme ohne Speichersorgen)

### Tasks

- [ ] Implement `silvasonic/processor/janitor.py` — `Janitor` class:
  - Periodic disk usage check (configurable interval from `ProcessorSettings.janitor_interval_seconds`)
  - Monitor mount point of `/data/recorder` via `shutil.disk_usage()` or `psutil`
  - Implement three escalating retention modes:

    | Mode             | Threshold | Criteria                                                      | Log Level  |
    | ---------------- | --------- | ------------------------------------------------------------- | ---------- |
    | **Housekeeping** | > 70%     | `uploaded=true` AND `analysis_state` complete for all workers | `INFO`     |
    | **Defensive**    | > 80%     | `uploaded=true` (regardless of analysis)                      | `WARNING`  |
    | **Panic**        | > 90%     | **Oldest** files regardless of status                         | `CRITICAL` |

- [ ] Implement **Soft Delete** pattern:
  - Physically delete both `raw` and `processed` WAV files from disk
  - Update DB row: `local_deleted = TRUE` (preserve historical inventory)
  - Log each deletion: filename, reason, mode
- [ ] Implement **Panic Mode fallback**:
  - If DB is unreachable during Panic Mode, fall back to filesystem `mtime` for blind cleanup (oldest files first)
- [ ] Exclusive delete authority: only the Processor deletes Recorder files — enforced by RW mount on Recorder workspace (all others mount `:ro`, ADR-0009)
- [ ] Integrate Janitor as periodic async task in `ProcessorService.run()`
- [ ] Report retention metrics via `get_extra_meta()`:
  - `disk_usage_percent`, `current_mode` (idle/housekeeping/defensive/panic), `files_deleted_total`
- [ ] Update health component: `self.health.update_status("janitor", ...)`
- [ ] Unit tests: threshold evaluation, mode escalation, soft-delete logic, panic fallback, DB-offline scenario
- [ ] Integration test: simulate disk pressure → verify correct files are deleted and DB rows updated

---

## Phase 5: Configuration Seeding & Controller Integration

**Goal:** The Controller seeds `ProcessorSettings` defaults into `system_config` on startup, and the Processor reads them. Configuration changes via Web-Interface trigger a Processor restart via State Reconciliation.

**User Stories:** US-P03 (Speicherregeln anpassen)

### Tasks

- [ ] Uncomment `processor` settings block in `config/defaults.yml`:
  ```yaml
  processor:
    janitor_threshold_warning: 70.0
    janitor_threshold_critical: 80.0
    janitor_threshold_emergency: 90.0
    janitor_interval_seconds: 60
    indexer_poll_interval: 2.0
  ```
- [ ] Verify Controller's `ConfigSeeder` correctly seeds `processor` key into `system_config` table on startup (`INSERT ... ON CONFLICT DO NOTHING`)
- [ ] Verify `ProcessorSettings` Pydantic schema defaults match YAML seed values (CI test from ADR-0023)
- [ ] Add `processor` entry to `system_services` table seed (Controller seeder):
  - `name = "processor"`, `enabled = true`, `status = "unknown"`
- [ ] Add Processor workspace directory (`processor/`) to `scripts/init.py` initialization
- [ ] Unit tests: seeding idempotence, settings round-trip (YAML → DB → Pydantic)
- [ ] Integration test: fresh DB → Controller seeds → Processor reads correct settings

---

## Phase 6: Robustness & End-to-End Verification

**Goal:** Verify end-to-end pipeline from Recorder output to database registration, and ensure the Processor survives infrastructure failures.

**User Stories:** US-P01, US-P02, US-P04 (Pipeline-Status)

### Tasks

- [ ] System test: Recorder produces WAV segments → Processor Indexer picks them up → recordings appear in DB
- [ ] Test: Redis outage does not stop indexing or cleanup (Critical Path has zero Redis dependency)
- [ ] Test: DB outage during Housekeeping/Defensive → Janitor skips (no data loss)
- [ ] Test: DB outage during Panic → Janitor falls back to filesystem-based cleanup
- [ ] Test: DB outage during Panic → blind delete → DB recovers → Processor restart → Reconciliation Audit heals orphaned rows (`local_deleted = true`)
- [ ] Test: Processor restart → resumes indexing without duplicates (idempotent)
- [ ] Test: concurrent Recorders (multiple microphones) → all indexed independently
- [ ] Verify heartbeat payload contains Processor-specific metrics (indexer + janitor status)
- [ ] Update Processor `README.md` with implemented features and status
- [ ] Update `ROADMAP.md`: mark v0.5.0 as `🔨 In Progress`
- [ ] `just check-all` passes (full CI pipeline)

---

## Out of Scope (Deferred)

| Item                                                 | Target Version |
| ---------------------------------------------------- | -------------- |
| BirdNET analysis worker                              | v0.9.0         |
| BatDetect analysis worker                            | v1.3.0         |
| Uploader service (FLAC compression, remote sync)     | v0.6.0         |
| Web-Interface (Dashboard, settings UI)               | v0.8.0         |
| Redis `PUBLISH` optimization for instant worker wake | post-v1.0.0    |
| TimescaleDB continuous aggregates                    | post-v1.0.0    |
| Archive-before-delete safety                         | post-v1.0.0    |
| Live Opus stream (Recorder → Icecast)                | v1.1.0         |

> **Note:** The ROADMAP.md scope for v0.5.0 mentions "Local Inference (BirdNET & BatDetect models)" — BirdNET is now scheduled for **v0.9.0** (pre-MVP) and BatDetect for v1.3.0 (post-MVP). This milestone focuses on the critical Processor infrastructure that all workers depend on. The Processor's Indexer and Janitor are prerequisites for any analysis worker (ADR-0018).
>
> **Note:** US-P03 (settings via Web-Interface) requires both the Processor (this milestone) and the Web-Interface (v0.8.0). This milestone implements the backend support (config seeding, read-on-startup). The UI will be added in v0.8.0.
>
> **Note:** US-P04 (pipeline status in dashboard) requires the Web-Interface (v0.8.0). This milestone ships the heartbeat payload with the required metrics. The dashboard visualization is deferred.
