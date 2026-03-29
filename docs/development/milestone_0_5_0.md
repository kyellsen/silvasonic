# Milestone v0.5.0 — Analysis & Backend Orchestration

> **Target:** v0.5.0 — Processor Service (Indexer + Janitor), `recordings` Schema & Indices, Processor Config Seeding, Controller Integration
>
> **Status:** ✅ Done
>
> **References:** [ADR-0009](../adr/0009-zero-trust-data-sharing.md), [ADR-0011](../adr/0011-audio-recording-strategy.md), [ADR-0018](../adr/0018-worker-pull-orchestration.md), [ADR-0019](../adr/0019-unified-service-infrastructure.md), [ADR-0023](../adr/0023-configuration-management.md), [ADR-0025](../adr/0025-recordings-standard-table.md), [Processor Service Spec](../services/processor.md), [Service Blueprint](service_blueprint.md)
>
> **User Stories:** [US-P01](../user_stories/processor.md#us-p01), [US-P02](../user_stories/processor.md#us-p02), [US-P03](../user_stories/processor.md#us-p03), [US-P04](../user_stories/processor.md#us-p04)

---

## Phase 1: Processor Service Skeleton & Compose Integration

**Goal:** Create the Processor service following the Service Blueprint, integrate into Compose as a Tier 1 service, and verify basic lifecycle (health, heartbeat, graceful shutdown).

**User Stories:** —

### Tasks

- [x] Scaffold `services/processor/` following the Service Blueprint (§1):
  - `Containerfile`, `pyproject.toml`, `README.md`
  - `src/silvasonic/processor/__init__.py`, `__main__.py`, `py.typed`
  - `tests/unit/`, `tests/integration/`
- [x] Implement `ProcessorService(SilvaService)` in `__main__.py`:
  - `service_name = "processor"`, `service_port = 9200`
  - Override `run()` with placeholder logic (Phase 3+4 fill this in)
  - Read `ProcessorSettings` from `system_config` table on startup (single DB read, Immutable Container pattern, ADR-0019)
- [x] Register in workspace:
  - Root `pyproject.toml`: add `silvasonic-processor` to `[project] dependencies` and `[tool.uv.sources]`
- [x] Add `Containerfile` following the Service Blueprint (§5):
  - Base: `python:3.11-slim-bookworm`
  - System deps: `curl`, `libsndfile1` (WAV metadata via `soundfile`)
  - Port: `9200`
- [x] Add Processor to `compose.yml` as Tier 1 service:
  - `container_name: silvasonic-processor`
  - Depends on `database` (healthy)
  - Mount Recorder workspace **read-write** (`${SILVASONIC_WORKSPACE_PATH}/recorder:/data/recorder:z`) — Processor is the **only** non-Recorder service with `:rw` access (Janitor delete authority, ADR-0009)
  - Mount Processor workspace read-write (`${SILVASONIC_WORKSPACE_PATH}/processor:/data/processor:z`)
  - Redis URL, DB env vars
  - Healthcheck on `:9200/healthy`
- [x] Add `compose.override.yml` dev mounts for hot-reload
- [x] Add `SILVASONIC_PROCESSOR_PORT=9200` to `.env.example`
- [x] `just check` passes

### Tests

#### Unit (`services/processor/tests/unit/`) — `@pytest.mark.unit`

- [x] `test_processor.py` — `TestProcessorService`
  - `test_package_import` — `import silvasonic.processor` succeeds
  - `test_service_name_and_port` — `service_name == "processor"`, `service_port == 9200`
  - `test_lifecycle_start_shutdown` — `ProcessorService` starts, shutdown signal triggers clean exit (mocked DB/Redis)
  - `test_settings_loaded_from_db` — Pydantic `ProcessorSettings` correctly deserialized from mock `system_config` row
  - `test_settings_defaults` — `ProcessorSettings()` defaults match `config/defaults.yml` values

#### Integration (`services/processor/tests/integration/`) — `@pytest.mark.integration`

- [x] `test_processor_lifecycle.py` — `TestProcessorLifecycle`
  - `test_processor_starts_with_db` — Processor starts in Testcontainer with real DB, `/healthy` returns 200 with `{"status": "ok"}`
  - `test_processor_heartbeat_published` — Processor publishes heartbeat to Redis within 15s

#### Smoke (`tests/smoke/`) — `@pytest.mark.smoke`

- [x] `test_health.py` — `TestServiceHealth::test_processor_healthy` + `TestServiceHeartbeats::test_processor_heartbeat_in_redis`

---

## Phase 2: Database Schema Enhancements

**Goal:** Finalize the `recordings` table schema and add indices for Worker Pull (ADR-0018) and Upload polling (v0.6.0 prep) — before the Indexer writes to this table.

**User Stories:** —

> **Decision (ADR-0025):** `recordings` remains a **standard PostgreSQL table** (no Hypertable). FK constraints from `detections` and `uploads` are preserved. Data volume (~2M rows/year) does not require partitioning. See [ADR-0025](../adr/0025-recordings-standard-table.md).

### Tasks

- [x] Add partial index for Worker Pull pattern (ADR-0018):
  ```sql
  CREATE INDEX ix_recordings_analysis_pending
  ON recordings (time ASC)
  WHERE local_deleted = false;
  ```
- [x] Add partial index for Upload polling (v0.6.0 preparation):
  ```sql
  CREATE INDEX ix_recordings_upload_pending
  ON recordings (time ASC)
  WHERE uploaded = false AND local_deleted = false;
  ```
- [x] Verify `analysis_state` JSONB column supports the Worker Pull `SELECT ... FOR UPDATE SKIP LOCKED` pattern efficiently
- [x] Update `services/database/init/01-init-schema.sql` with new indices
- [x] Update SQLAlchemy ORM models in `silvasonic.core.database.models` if schema changes apply

### Tests

#### Unit (`packages/core/tests/unit/`) — `@pytest.mark.unit`

- [x] `test_recording_model.py` — `TestRecordingModel`
  - `test_analysis_state_default_empty_jsonb` — new `Recording()` has `analysis_state == {}`
  - `test_local_deleted_default_false` — new `Recording()` has `local_deleted == False`
  - `test_uploaded_default_false` — new `Recording()` has `uploaded == False`

#### Integration (`tests/integration/`) — `@pytest.mark.integration`

- [x] `test_worker_pull_query.py` — `TestWorkerPullQuery`
  - `test_for_update_skip_locked` — Two concurrent sessions: first locks a row, second gets a different row via `SKIP LOCKED`
  - `test_partial_index_used` — `EXPLAIN` confirms `ix_recordings_analysis_pending` index is used
  - `test_upload_pending_index` — `EXPLAIN` confirms `ix_recordings_upload_pending` index is used

---

## Phase 3: Indexer — Filesystem Polling & Recording Registration

**Goal:** The Indexer scans the Recorder workspace for promoted WAV files, extracts metadata, and registers them in the `recordings` table. Recordings appear in the database within seconds of being written to disk.

**User Stories:** US-P01 (Aufnahmen erscheinen automatisch)

### Tasks

- [x] Implement `silvasonic/processor/indexer.py` — `Indexer` class:
  - Periodic filesystem polling of all `recorder/*/data/processed/*.wav` (configurable interval from `ProcessorSettings.indexer_poll_interval`, default: `2.0` seconds)
  - Extract WAV metadata via `soundfile`: duration, sample_rate, channels, file size
  - Determine `sensor_id` from directory structure (`recorder/{device_name}/data/...`)
  - Locate corresponding raw file: `recorder/{device_name}/data/raw/{same_filename}.wav`
  - Calculate `filesize_raw` from the raw file
- [x] Register each new WAV in the `recordings` table:
  - `time`: parsed from segment filename (ISO timestamp)
  - `sensor_id`: device name from directory path
  - `file_raw`, `file_processed`: relative paths to both streams
  - `duration`, `sample_rate`, `filesize_raw`, `filesize_processed`
  - `uploaded = false`, `local_deleted = false`
  - `analysis_state = '{}'::jsonb` (empty — no workers have processed it yet)
  - Idempotent: check for existing entry by `file_processed` before insert (avoid duplicates)
- [x] Only index files from `data/` directories — never from `.buffer/` (only complete, promoted segments)
- [x] Integrate Indexer as periodic async task in `ProcessorService.run()`
- [x] Report indexing metrics via `get_extra_meta()` for heartbeat:
  - `last_indexed_at`, `pending_count` (files on disk not yet in DB), `total_indexed`
- [x] Update health component: `self.health.update_status("indexer", True/False, details)`
- [x] Implement **Filesystem Reconciliation Audit** (Split-Brain Healing):
  - Runs once on Processor startup, before the Indexer polling loop begins
  - Queries all `recordings` rows where `local_deleted = false`
  - Verifies `file_processed` exists on the filesystem
  - If file is missing: sets `local_deleted = true` and logs at `WARNING` level with reason `"reconciliation"`
  - Reports `reconciled_count` in startup log and heartbeat metrics
  - Rationale: Heals Split-Brain state caused by Panic-Mode blind deletion (Phase 4) during DB outages
### Tests

#### Unit (`services/processor/tests/unit/`) — `@pytest.mark.unit`

- [x] `test_indexer.py` — `TestIndexer`
  - `test_wav_metadata_extraction` — `soundfile.info()` returns correct duration, sample_rate, channels from a synthetic WAV
  - `test_sensor_id_from_path` — path `recorder/ultramic-01/data/processed/seg.wav` extracts `sensor_id == "ultramic-01"`
  - `test_timestamp_from_filename` — ISO-timestamp filename parsed correctly
  - `test_raw_file_path_resolution` — given processed path, resolves corresponding raw path
  - `test_idempotent_skip_existing` — file already in DB (mocked) is not re-inserted
  - `test_buffer_dir_excluded` — files in `.buffer/` are never indexed
  - `test_only_data_dir_scanned` — only `data/processed/` is scanned, not parent or sibling dirs
- [x] `test_reconciliation.py` — `TestReconciliationAudit`
  - `test_missing_file_marked_deleted` — DB row with `local_deleted=false`, file absent → sets `local_deleted=true`
  - `test_existing_file_unchanged` — DB row with `local_deleted=false`, file present → no change
  - `test_already_deleted_row_skipped` — DB row with `local_deleted=true` is not re-checked
  - `test_reconciled_count_reported` — returns correct count of reconciled rows

#### Integration (`services/processor/tests/integration/`) — `@pytest.mark.integration`

- [x] `test_indexer_e2e.py` — `TestIndexerIntegration`
  - `test_new_wav_indexed` — place WAV files in mock workspace → Indexer picks them up → verify `recordings` rows in DB (Testcontainer PostgreSQL)
  - `test_idempotent_reindex` — run Indexer twice on same files → no duplicate `recordings` rows
  - `test_multiple_sensors_indexed` — files from two sensor directories → correct `sensor_id` per row
- [x] `test_reconciliation_e2e.py` — `TestReconciliationIntegration`
  - `test_orphaned_rows_healed` — seed DB with `local_deleted=false` rows, remove files from disk → Reconciliation Audit marks them `local_deleted=true`
  - `test_valid_rows_preserved` — seed DB with `local_deleted=false` rows, files exist → no changes

---

## Phase 4: Janitor — Data Retention & Storage Management

**Goal:** The Janitor monitors NVMe disk utilization and enforces the escalating retention policy (ADR-0011 §6) to prevent storage exhaustion. The Recorder never stops due to a full disk.

**User Stories:** US-P02 (Endlos-Aufnahme ohne Speichersorgen)

### Tasks

- [x] Implement `silvasonic/processor/janitor.py` — `Janitor` class:
  - Periodic disk usage check (configurable interval from `ProcessorSettings.janitor_interval_seconds`)
  - Monitor mount point of `/data/recorder` via `shutil.disk_usage()`
  - Implement three escalating retention modes:

    | Mode             | Threshold | Criteria                                                      | Log Level  |
    | ---------------- | --------- | ------------------------------------------------------------- | ---------- |
    | **Housekeeping** | > 70%     | `uploaded=true` AND `analysis_state` complete for all workers | `INFO`     |
    | **Defensive**    | > 80%     | `uploaded=true` (regardless of analysis)                      | `WARNING`  |
    | **Panic**        | > 90%     | **Oldest** files regardless of status                         | `CRITICAL` |

- [x] Implement **Soft Delete** pattern:
  - Physically delete both `raw` and `processed` WAV files from disk
  - Update DB row: `local_deleted = TRUE` (preserve historical inventory)
  - Log each deletion: filename, reason, mode
- [x] Implement **Panic Mode fallback**:
  - If DB is unreachable during Panic Mode, fall back to filesystem `mtime` for blind cleanup (oldest files first)
- [x] Implement **Uploader-Fallback**: When no Uploader is configured (no active `storage_remotes` rows), skip `uploaded` condition in Housekeeping/Defensive. Logged at WARNING with `janitor.uploader_fallback_active`
- [x] Implement **Batch Size Limit**: `janitor_batch_size` (default 50) per cleanup cycle. Add to `ProcessorSettings`
- [x] Exclusive delete authority: only the Processor deletes Recorder files — enforced by RW mount on Recorder workspace (all others mount `:ro`, ADR-0009)
- [x] Integrate Janitor as periodic async task in `ProcessorService.run()`
- [x] Report retention metrics via `get_extra_meta()`:
  - `disk_usage_percent`, `current_mode` (idle/housekeeping/defensive/panic), `files_deleted_total`
- [x] Update health component: `self.health.update_status("janitor", ...)`

### Tests

#### Unit (`services/processor/tests/unit/`) — `@pytest.mark.unit`

- [x] `test_janitor.py` — `TestEvaluateMode`, `TestFindDeletable`, `TestDeleteFiles`, `TestSoftDelete`, `TestPanicFilesystemFallback`, `TestRunCleanup`
  - `test_idle_below_all_thresholds` — 60% usage → mode `idle`, no deletions
  - `test_housekeeping_mode_triggers` — 75% usage → mode `housekeeping`
  - `test_defensive_mode_triggers` — 85% usage → mode `defensive`
  - `test_panic_mode_triggers` — 95% usage → mode `panic`
  - `test_housekeeping_criteria_with_uploader` — only deletes `uploaded=true AND analysis_state complete`
  - `test_housekeeping_no_uploader_fallback` — no `storage_remotes` → skips `uploaded` check
  - `test_defensive_criteria_with_uploader` — deletes `uploaded=true` regardless of analysis
  - `test_defensive_no_uploader_fallback` — no `storage_remotes` → deletes all non-deleted
  - `test_panic_criteria` — deletes oldest files regardless of status
  - `test_soft_delete_updates_db` — physical delete + DB row `local_deleted=true` (mocked fs/DB)
  - `test_panic_fallback_no_db` — DB unreachable → falls back to `mtime`-based filesystem cleanup
  - `test_db_offline_housekeeping_skips` — DB offline during Housekeeping → skips (no data loss)
  - `test_metrics_reported` — `disk_usage_percent`, `current_mode`, `files_deleted_total` in heartbeat extras
  - `test_batch_size_respected` — max N files per LIMIT parameter

#### Integration (`services/processor/tests/integration/`) — `@pytest.mark.integration`

- [x] `test_janitor_e2e.py` — `TestJanitorIntegration`
  - `test_housekeeping_deletes_correct_files` — seed DB + filesystem, mock `shutil.disk_usage` at 75% → only uploaded+analyzed files deleted, DB rows updated
  - `test_defensive_deletes_uploaded_only` — mock 85% → uploaded files deleted regardless of analysis state
  - `test_panic_deletes_oldest` — mock 95% → oldest files deleted regardless of status
  - `test_panic_filesystem_fallback` — mock 95% + DB offline → files deleted by `mtime`, DB untouched

---

## Phase 5: Configuration Seeding & Controller Integration

**Goal:** The Controller seeds `ProcessorSettings` defaults into `system_config` on startup, and the Processor reads them. Configuration changes via Web-Interface trigger a Processor restart via State Reconciliation.

**User Stories:** US-P03 (Speicherregeln anpassen)

### Tasks

- [x] Uncomment `processor` settings block in `config/defaults.yml`:
  ```yaml
  processor:
    janitor_threshold_warning: 70.0
    janitor_threshold_critical: 80.0
    janitor_threshold_emergency: 90.0
    janitor_interval_seconds: 60
    janitor_batch_size: 50
    indexer_poll_interval: 2.0
  ```
- [x] Verify Controller's `ConfigSeeder` correctly seeds `processor` key into `system_config` table on startup (`INSERT ... ON CONFLICT DO NOTHING`)
- [x] Verify `ProcessorSettings` Pydantic schema defaults match YAML seed values (CI test from ADR-0023)
- ~~Add `processor` entry to `system_services` table seed~~ → **Deferred to [v0.8.0](milestone_0_8_0.md)** (no consumer until Web-Interface)
- [x] Add Processor workspace directory (`processor/`) to `scripts/init.py` initialization
### Tests

#### Unit (`services/controller/tests/unit/`) — `@pytest.mark.unit`

- [x] `test_seeder.py` (extend existing) — `TestConfigSeeder::test_seed_inserts_defaults`
  - `test_seed_inserts_defaults` — `ConfigSeeder` inserts all 4 schema_map keys (`system`, `processor`, `uploader`, `birdnet`) with correct defaults
  - `test_seed_skips_existing_values` — seeding twice does not overwrite existing values
- [x] `test_seeder.py` — `TestDefaultsYamlParity` (drift guard)
  - `test_yaml_keys_covered_by_schema_map` — every YAML config key has a schema_map entry
  - `test_schema_map_keys_present_in_yaml` — every schema_map key exists in defaults.yml
  - `test_all_yaml_values_pass_pydantic_validation` — every YAML section validates against its Pydantic schema

#### Unit (`services/processor/tests/unit/`) — `@pytest.mark.unit`

- [x] `test_processor.py` — `TestProcessorSettings`
  - `test_settings_defaults` — `ProcessorSettings()` defaults match config/defaults.yml values
  - `test_settings_round_trip` — serialize to JSON → deserialize → identical Pydantic model

#### Integration (`services/controller/tests/integration/`) — `@pytest.mark.integration`

- [x] `test_seeder.py` (existing) — `TestConfigSeederIntegration`
  - `test_seed_inserts_system_config` — fresh DB → Controller seeds → `system_config` contains keys with correct JSONB
  - `test_seed_is_idempotent` — seeding twice does not overwrite
- [x] `test_processor_lifecycle.py` — `TestProcessorLifecycle::test_processor_starts_with_db` — Processor reads seeded settings from DB
  - ~~`test_processor_system_service_registered`~~ → **Deferred to [v0.8.0](milestone_0_8_0.md)**

---

## Phase 6: Robustness & End-to-End Verification

**Goal:** Verify end-to-end pipeline from Recorder output to database registration, and ensure the Processor survives infrastructure failures.

**User Stories:** US-P01, US-P02, US-P04 (Pipeline-Status)

### Tasks

- [x] Verify heartbeat payload contains Processor-specific metrics (indexer + janitor status)
- [x] Update Processor `README.md` with implemented features and status
- [x] Update `ROADMAP.md`: mark v0.5.0 as `🔨 In Progress`
- [x] `just check-all` passes (full CI pipeline)

### Tests

#### System (`tests/system/`) — `@pytest.mark.system`

- [x] `test_processor_lifecycle.py` — `TestProcessorLifecycle`
  - `test_recorder_to_processor_pipeline` ✅
  - `test_processor_restart_idempotent` ✅
  - `test_concurrent_recorders_indexed` ✅
  - `test_heartbeat_has_processor_metrics` ✅
- [x] `test_processor_resilience.py` — `TestProcessorResilience`
  - `test_redis_outage_indexing_continues` ✅
  - `test_redis_outage_janitor_continues` ✅
  - `test_db_outage_housekeeping_skips` ✅
  - `test_db_outage_panic_filesystem_fallback` ✅
  - `test_split_brain_healing` ✅

#### Smoke (`tests/smoke/`) — `@pytest.mark.smoke`

- [x] `test_health.py` — `TestServiceHealth`
  - `test_processor_healthy` ✅
- [x] `test_health.py` — `TestServiceHeartbeats`
  - `test_processor_heartbeat_in_redis` ✅

#### System HW (`tests/system/`) — `@pytest.mark.system_hw`

> **Note:** Only if v0.5.0 changes affect device detection or Recorder interaction. Recommended but not mandatory.

- [x] `test_hw_recording.py` (extend existing) — `TestFullPipelineE2E`
  - `test_hw_recorder_to_processor_pipeline` — real USB mic → Recorder → WAV → Processor Indexer → DB recordings ✅ (implemented, requires `just test-hw`)

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
