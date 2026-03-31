# Milestone v0.6.0 — Uploader (FLAC Compression & Cloud Sync)

> **Target:** v0.6.0 — Uploader Service: FLAC compression, Rclone-based multi-target upload, Controller-managed Tier 2 container lifecycle, Audit logging, Janitor integration
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0004](../adr/0004-use-podman.md), [ADR-0007](../adr/0007-rootless-os-compliance.md), [ADR-0009](../adr/0009-zero-trust-data-sharing.md), [ADR-0010](../adr/0010-naming-conventions.md), [ADR-0011](../adr/0011-audio-recording-strategy.md), [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0018](../adr/0018-worker-pull-orchestration.md), [ADR-0019](../adr/0019-unified-service-infrastructure.md), [ADR-0020](../adr/0020-resource-limits-qos.md), [ADR-0023](../adr/0023-configuration-management.md), [ADR-0024](../adr/0024-ffmpeg-audio-engine.md), [Uploader Service Spec](../services/uploader.md), [Service Blueprint](service_blueprint.md), [Testing Guidelines](testing.md)
>
> **User Stories:** [US-U01](../user_stories/uploader.md#us-u01), [US-U02](../user_stories/uploader.md#us-u02), [US-U03](../user_stories/uploader.md#us-u03), [US-U06](../user_stories/uploader.md#us-u06)
>
> **Project Rules:** [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [Glossary](../glossary.md)

---

## Architecture Overview

The Uploader is an **immutable Tier 2** service managed by the Controller via `podman-py` (ADR-0013). The Controller creates **one Uploader container per active `storage_remotes` row** — the same pattern as one Recorder per Device.

### Recorder vs. Uploader

| Aspect | Recorder | Uploader |
|---|---|---|
| **Config Source** | Profile Injection (env var `CONFIG_JSON`) | DB direct read (`storage_remotes`, `system_config`) |
| **DB Access** | ❌ None | ✅ read `recordings`, `storage_remotes`, `system_config`; write `uploads`, `recordings.uploaded` |
| **Identity Source** | `devices` table → `Device` model | `storage_remotes` table → `StorageRemote` model |
| **Container Name** | `silvasonic-recorder-{slug}-{suffix}` | `silvasonic-uploader-{remote_slug}` |
| **Label `device_id`** | Hardware device name | Remote storage slug |
| **Workspace Mount** | RW (Producer, ADR-0009) | RO (Consumer Principle, ADR-0009) |
| **Privileged/Audio** | Yes + `/dev/snd` + audio group | No |
| **Health Port** | 9500 (unified Tier 2) | 9500 (unified Tier 2) |
| **OOM Score** | -999 (Protected) | 250 (Low Priority, ADR-0020) |
| **Resources** | 512m / 1.0 CPU | 256m / 0.5 CPU |
| **System Deps** | ffmpeg | ffmpeg + rclone |

### Controller — What Changes vs. What Stays

**No changes needed (already generic):**

- `ContainerManager` — accepts any `Tier2ServiceSpec`
- `ContainerManager.sync_state()` — compares desired vs actual, service-agnostic
- `ReconciliationLoop.run()` — calls `evaluate()` → `sync_state()`
- `ControllerStats` — records starts/stops by name, no service-type knowledge
- `LogForwarder` — attaches to all `io.silvasonic.owner=controller` containers
- `NudgeSubscriber` — triggers reconciliation via same nudge channel
- `_stop_all_tier2()` — stops all `list_managed()` on shutdown

**Minimal extensions (Phase 2):**

- `container_spec.py` — new factory `build_uploader_spec()` + `UploaderEnvConfig`
- `reconciler.py` — `DeviceStateEvaluator.evaluate()` returns Recorder **+** Uploader specs

### Remote Path Convention

The Uploader constructs the remote path from DB fields — no changes to the local Recorder layout.

**Local (resolved via DB, Janitor cleans up):**
```
Local paths are resolved by joining the mounted recorder workspace root with recordings.file_raw (stored as relative path in the database).
```

**Remote (date-based archive, permanent):**
```
silvasonic/{station_name}/{sensor_id}/{YYYY-MM-DD}/{filename}.flac
```

**Example:**
```
Local:   /workspace/recorder/ultramic-01/data/raw/raw_20260329_143000.wav
Remote:  silvasonic/Silvasonic-Dev/ultramic-01/2026-03-29/raw_20260329_143000.flac
```

The `path_builder` module (Phase 3) is the **only component** that knows about the date-based directory convention.
It reads `recordings.time` for the date, `recordings.sensor_id` for the microphone, and `system_config.station_name` for the station prefix.

The `silvasonic/` top-level prefix prevents collision with other data in the same cloud storage account — critical when multiple stations upload to the same Nextcloud.

---

## Phase 1: Uploader Service Skeleton

**Goal:** Create the Uploader service following the Service Blueprint. The service starts, exposes `/healthy`, publishes heartbeats, and shuts down cleanly. No upload logic yet — `run()` contains a placeholder loop.

**User Stories:** —

**Dependency:** None — first phase.

### Source References

> **Read these files before starting Phase 1:**

| Purpose | File |
|---|---|
| Service base class (inherit from this) | `packages/core/src/silvasonic/core/service.py` |
| Service context (Redis, Health, Heartbeat) | `packages/core/src/silvasonic/core/service_context.py` |
| Recorder `__main__.py` — pattern to copy | `services/recorder/src/silvasonic/recorder/__main__.py` |
| Recorder `settings.py` — pattern to copy | `services/recorder/src/silvasonic/recorder/settings.py` |
| UploaderSettings schema | `packages/core/src/silvasonic/core/config_schemas.py` |
| Processor `pyproject.toml` — packaging pattern | `services/processor/pyproject.toml` |
| Processor `Containerfile` — container pattern | `services/processor/Containerfile` |
| Service Blueprint — scaffold rules | `docs/development/service_blueprint.md` |
| Naming conventions (ADR-0010) | `docs/adr/0010-naming-conventions.md` |
| Podman rootless (ADR-0004, ADR-0007) | `docs/adr/0004-use-podman.md`, `docs/adr/0007-rootless-os-compliance.md` |
| Test guidelines (markers, structure) | `docs/development/testing.md` |
| Root test config | `pyproject.toml` (pytest section), `conftest.py` |

### Tasks

- [ ] **Prerequisite: Move `Upload` model** from `packages/core/src/silvasonic/core/database/models/system.py` to `packages/core/src/silvasonic/core/database/models/uploader.py`:
  - Move `class Upload(Base)` out of `system.py` into `uploader.py` (alongside `StorageRemote`)
  - Update all imports across the codebase (`system.py` → `uploader.py`)
  - Verify `just check` passes after the move
- [ ] **Prerequisite: Add `batch_size` to `UploaderSettings`** in `packages/core/src/silvasonic/core/config_schemas.py`:
  - Add field: `batch_size: int = 50` to `UploaderSettings`
  - Add `batch_size: 50` to `services/controller/config/defaults.yml` under `uploader:` section
- [ ] Scaffold `services/uploader/` following the Service Blueprint (§1):
  - `Containerfile`, `pyproject.toml`, `README.md`
  - `src/silvasonic/uploader/__init__.py`, `__main__.py`, `settings.py`, `py.typed`
  - `tests/unit/`, `tests/integration/`
- [ ] Implement `UploaderService(SilvaService)` in `__main__.py`:
  - `service_name = "uploader"`, `service_port = 9500` (unified Tier 2 health port)
  - Override `run()` with placeholder polling loop (Phase 3 fills this in)
  - Override `load_config()`: read `UploaderSettings` from `system_config` table on startup (Immutable Container pattern, ADR-0019)
  - Read assigned `StorageRemote` config from DB by `SILVASONIC_STORAGE_REMOTE_SLUG` env var
- [ ] Implement `settings.py` — `UploaderServiceSettings(BaseSettings)`:
  - `SILVASONIC_REDIS_URL`, `SILVASONIC_INSTANCE_ID`, `SILVASONIC_STORAGE_REMOTE_SLUG`
- [ ] Register in workspace:
  - Root `pyproject.toml`: add `silvasonic-uploader` to `[project] dependencies` and `[tool.uv.sources]`
- [ ] Add `Containerfile` following the Service Blueprint (§5):
  - Base: `python:3.13-slim-bookworm`
  - System deps: `curl`, `ffmpeg` (FLAC encoding), `rclone` (upload backend)
  - Port: `EXPOSE 9500` — **NOT** 9200 like Processor. Uploader uses the unified Tier 2 health port (same as Recorder)
- [ ] **NO** runtime `compose.yml` entry — Uploader is Tier 2, managed by Controller (ADR-0013, Service Blueprint §6)
- [ ] Add Uploader build-template to `compose.yml` under `profiles: [managed]` (build-only, NOT for runtime — same pattern as Recorder entry at line 110-137 in `compose.yml`):
  - This enables `scripts/build.py` to build the image via `compose --profile managed build`
  - Add `"uploader"` to `MANAGED_SERVICES` list in `scripts/build.py` (alongside `"recorder"`)
- [ ] **NO** `workspace_dirs.txt` entry — Uploader has no persistent workspace (reads Recorder workspace as `:ro`, temporary FLAC files use in-container `/tmp`)

### Acceptance Criteria

> Phase is complete when `just check` passes and all tests below are green.

#### Unit Tests (`services/uploader/tests/unit/test_uploader.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_package_import` | `import silvasonic.uploader` succeeds |
| `test_service_name_and_port` | `service_name == "uploader"`, `service_port == 9500` |
| `test_lifecycle_start_shutdown` | `UploaderService` starts, SIGTERM triggers clean exit (mocked DB/Redis) |
| `test_settings_loaded_from_db` | `UploaderSettings` correctly deserialized from mock `system_config` row |
| `test_settings_defaults` | `UploaderSettings()` defaults match `config/defaults.yml` values |
| `test_storage_remote_loaded` | `StorageRemote` read from mock DB by slug env var |
| `test_main_guard` | `__main__` guard calls `UploaderService().start()` (runpy) |

#### Integration Tests (`services/uploader/tests/integration/test_uploader_lifecycle.py`) — `@pytest.mark.integration`

| Test | Validates |
|---|---|
| `test_uploader_starts_with_db` | Uploader starts with Testcontainer DB, `/healthy` returns `200` |
| `test_uploader_heartbeat_published` | Heartbeat published to Redis within 15s |

---

## Phase 2: Controller Integration

**Goal:** Extend the Controller to manage Uploader containers as Tier 2 instances. One Uploader per active `storage_remotes` row. No Uploader business logic — only container lifecycle management.

**User Stories:** US-U03 (Mehrere Speicherziele gleichzeitig)

**Dependency:** Phase 1 (Uploader image must exist for container specs).

### Source References

> **Read these files before starting Phase 2:**

| Purpose | File |
|---|---|
| Container spec factory (extend this) | `services/controller/src/silvasonic/controller/container_spec.py` |
| Reconciler / evaluator (extend this) | `services/controller/src/silvasonic/controller/reconciler.py` |
| ContainerManager (generic, no changes needed) | `services/controller/src/silvasonic/controller/container_manager.py` |
| Controller settings | `services/controller/src/silvasonic/controller/settings.py` |
| Defaults YAML (schedule, bandwidth) |  `services/controller/config/defaults.yml` |
| Tier 2 management (ADR-0013) | `docs/adr/0013-tier2-container-management.md` |
| Resource limits / QoS (ADR-0020) | `docs/adr/0020-resource-limits-qos.md` |
| Existing spec tests — pattern to extend | `services/controller/tests/unit/test_container_spec.py` |
| Existing reconciler tests — pattern to extend | `services/controller/tests/unit/test_reconciler.py` |
| Controller conftest (DB cleanup order) | `services/controller/tests/conftest.py` |

### Tasks

- [ ] Add `build_uploader_spec()` factory + `UploaderEnvConfig` to `container_spec.py`:
  - Import `StorageRemote` from `silvasonic.core.database.models.uploader`
  - `UploaderEnvConfig(BaseSettings)` — env defaults: image, memory, CPU, network, workspace, DB connection
  - Build `Tier2ServiceSpec` with:
    - Image: `localhost/silvasonic_uploader:latest`
    - Name: `silvasonic-uploader-{remote.slug}`
    - Labels: `io.silvasonic.tier=2`, `io.silvasonic.owner=controller`, `io.silvasonic.service=uploader`, `io.silvasonic.device_id={slug}`
    - Environment: `SILVASONIC_STORAGE_REMOTE_SLUG`, `SILVASONIC_REDIS_URL`, `SILVASONIC_INSTANCE_ID`, DB connection vars (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`)
    - Mounts: **Single mount** of the entire recorder workspace — `{host_workspace}/recorder → /workspace/recorder:ro,z` (KISS: one mount covers all recorders, Uploader resolves exact file paths by joining the `/workspace/recorder` root with the relative path stored in `recordings.file_raw`, Consumer Principle ADR-0009)
    - Resources: `memory_limit=256m`, `cpu_limit=0.5`, `oom_score_adj=250` (ADR-0020)
    - **No** `devices`, `group_add`, `privileged` (unlike Recorder)
- [ ] Refactor `DeviceStateEvaluator.evaluate()` in `reconciler.py`:
  - Extract existing logic into `_evaluate_recorders(session)` (rename only, no behavior change)
  - Add `_evaluate_uploaders(session)`:
    - **Early exit:** If `UploaderSettings.enabled == false` → return empty list (no containers started). This is the "global pause" — checked here, not inside the Uploader container
    - Query `StorageRemote` WHERE `is_active = true`
    - Respect `max_uploaders` from `SystemSettings` in `system_config`. If there are more active remotes than allowed, Controller must select deterministically by `created_at ASC, slug ASC`.
    - Build `Tier2ServiceSpec` via `build_uploader_spec()` per active remote
    - Skip remotes with invalid config → log warning (rate-limited via `_warned_remotes` set)
  - `evaluate()` returns combined list: `recorder_specs + uploader_specs`
- [ ] Update Controller docstring in `__main__.py`: mention "Tier 2 services (Recorder and Uploader instances)"
- [ ] Add `"uploads"` to `_CLEANUP_TABLES` in FK-safe order (`uploads` before `recordings`, before `storage_remotes`) in these 3 files:
  - `services/controller/tests/integration/conftest.py`
  - `services/processor/tests/integration/conftest.py`
  - `tests/integration/conftest.py`

### Acceptance Criteria

> Phase is complete when `just check` passes and all tests below are green.

#### Unit Tests (`services/controller/tests/unit/test_container_spec.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_uploader_spec_from_remote` | Valid `StorageRemote` → correct spec with all fields |
| `test_uploader_name_format` | Container name = `silvasonic-uploader-{slug}` |
| `test_uploader_labels` | `service=uploader`, `device_id={slug}`, `tier=2`, `owner=controller` |
| `test_uploader_readonly_mounts` | Recorder workspace mounted as `read_only=True` |
| `test_uploader_resource_limits` | `256m` memory, `0.5` CPU, `OOM=250` |
| `test_uploader_no_privileged_no_devices` | `privileged=False`, `devices=[]`, `group_add=[]` |
| `test_uploader_db_env_vars` | DB connection env vars present (`POSTGRES_HOST`, etc.) |
| `test_uploader_env_slug` | `SILVASONIC_STORAGE_REMOTE_SLUG` matches `remote.slug` |

#### Unit Tests (`services/controller/tests/unit/test_reconciler.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_evaluates_uploaders_from_active_remotes` | Active `StorageRemote` rows → Uploader specs |
| `test_inactive_remote_excluded` | `is_active=false` → no spec generated |
| `test_uploader_enabled_false_returns_empty` | `UploaderSettings.enabled=false` → 0 Uploader specs (global pause) |
| `test_max_uploaders_respected_order` | More remotes than `max_uploaders` → list truncated, ordered by `created_at ASC, slug ASC` |
| `test_combined_recorders_and_uploaders` | Devices + remotes → combined spec list |
| `test_missing_remote_config_logged` | Invalid config → warning logged, remote skipped |

#### Integration Tests (`services/controller/tests/integration/test_uploader_reconciliation.py`) — `@pytest.mark.integration`

| Test | Validates |
|---|---|
| `test_active_remote_produces_spec` | Seed `storage_remotes` row → evaluate → Uploader spec returned |
| `test_deactivated_remote_disappears` | Deactivate remote → re-evaluate → no Uploader spec |

---

## Phase 3: Upload Pipeline

**Goal:** Implement the complete upload pipeline: find pending recordings, compress WAV→FLAC, upload via rclone, log the attempt, update the database. This is one coherent domain — all modules exist to serve the pipeline and are tested together.

**User Stories:** US-U01 (Automatischer Cloud-Upload mit FLAC), US-U06 (Lückenlose Nachverfolgung)

**Dependency:** Phase 1 (Uploader service with `run()` placeholder).

### Modules

| Module | File | Responsibility |
|---|---|---|
| **Work Poller** | `work_poller.py` | Find recordings not yet uploaded to THIS remote (via `uploads` table) |
| **FLAC Encoder** | `flac_encoder.py` | WAV→FLAC via ffmpeg subprocess |
| **Path Builder** | `path_builder.py` | Build remote path from DB fields (date-based archive layout, station name slugified) |
| **Rclone Client** | `rclone_client.py` | Upload files via rclone subprocess |
| **Audit Logger** | `audit_logger.py` | Immutable `uploads` table + mark `recordings.uploaded` (Janitor signal) |
| **Upload Stats** | `upload_stats.py` | Two-Phase Logging: startup detail → periodic summary (mirrors RecordingStats pattern) |

### Source References

> **Read these files before starting Phase 3:**

| Purpose | File |
|---|---|
| RecordingStats — Two-Phase pattern to copy | `services/recorder/src/silvasonic/recorder/recording_stats.py` |
| ControllerStats — Two-Phase pattern reference | `services/controller/src/silvasonic/controller/controller_stats.py` |
| Recording DB model (query target) | `packages/core/src/silvasonic/core/database/models/recordings.py` |
| StorageRemote + Upload DB models (both in same file after Phase 1 move) | `packages/core/src/silvasonic/core/database/models/uploader.py` |
| SystemConfig model | `packages/core/src/silvasonic/core/database/models/system.py` |
| Async session factory | `packages/core/src/silvasonic/core/database/session.py` |
| UploaderSettings schema | `packages/core/src/silvasonic/core/config_schemas.py` |
| FFmpeg usage pattern (ADR-0024) | `docs/adr/0024-ffmpeg-audio-engine.md` |
| Worker Pull orchestration (ADR-0018) | `docs/adr/0018-worker-pull-orchestration.md` |
| Zero Trust / Consumer Principle (ADR-0009) | `docs/adr/0009-zero-trust-data-sharing.md` |
| Health monitor API | `packages/core/src/silvasonic/core/health.py` |
| Heartbeat publisher | `packages/core/src/silvasonic/core/heartbeat.py` |

### Tasks

- [ ] Implement `silvasonic/uploader/work_poller.py`:
  - `find_pending_uploads(session, remote_slug, batch_size) -> list[PendingUpload]`
  - **Per-remote query** — each Uploader only sees recordings not yet uploaded to ITS remote:
    ```sql
    SELECT r.* FROM recordings r
    WHERE r.local_deleted = false
      AND NOT EXISTS (
        SELECT 1 FROM uploads u
        WHERE u.recording_id = r.id
          AND u.remote_slug = :my_slug
          AND u.success = true
      )
    ORDER BY r.time ASC LIMIT :batch
    ```
  - Note for DB indexes: We strongly recommend adding a composite index on `uploads(recording_id, remote_slug, success)` for efficient polling.
  - `recordings.uploaded` is NOT used for polling — it is only the Janitor's deletion signal
  - `batch_size` default comes from `UploaderSettings.batch_size` (added in Phase 1 prerequisite, default: `50`)
  - `PendingUpload` Pydantic model: `recording_id, file_raw, sensor_id, time`
- [ ] Implement `silvasonic/uploader/flac_encoder.py`:
  - `encode_wav_to_flac(wav_path: Path, output_dir: Path) -> Path`
  - ffmpeg subprocess: `ffmpeg -i input.wav -c:a flac -compression_level 5 output.flac`
  - Validate output file (exists, non-zero size)
  - Clean up partial FLAC file on failure
  - No FLAC caching — re-encode on retry (KISS, encoding is <1s per segment on RPi 5)
- [ ] **Prerequisite: Add `python-slugify` dependency** to `packages/core/pyproject.toml`:
  - Add `"python-slugify>=8.0.0"` to `[project] dependencies`
  - Run `uv lock` to regenerate `uv.lock`
- [ ] Implement `silvasonic/uploader/path_builder.py`:
  - `build_remote_path(station_name, sensor_id, time, filename) -> str`
  - Convention: `silvasonic/{station_slug}/{sensor_id}/{YYYY-MM-DD}/{filename}.flac`
  - Date extracted from `recordings.time`, station name from `system_config`
  - **Station name slugified:** `from slugify import slugify` — lowercase, non-alphanumeric → `-`, strip leading/trailing `-`. Example: `"Silvasonic Müller-Station [Test]"` → `"silvasonic-mueller-station-test"`
  - This is the **only module** that knows the remote directory convention
- [ ] Implement `silvasonic/uploader/rclone_client.py`:
  - `RcloneClient(remote_slug, remote_type, config)`:
    - `generate_rclone_conf() -> Path` — write temp `rclone.conf` from `StorageRemote.config` JSONB
    - For WebDAV/Nextcloud: set `vendor = nextcloud`
    - `upload_file(local, remote_path, bandwidth_limit) -> RcloneResult`
    - `RcloneResult(success, bytes_transferred, error_message, duration_s, is_connection_error)`
    - `is_connection_error` distinguishes network failures (abort batch) from file-specific errors (skip file, continue)
    - Bandwidth limiting via `--bwlimit` from `UploaderSettings.bandwidth_limit`
    - Checksum verification via `--checksum` flag (rclone verifies post-upload integrity)
- [ ] Implement `silvasonic/uploader/audit_logger.py`:
  - `log_upload_attempt(session, recording_id, remote_slug, filename, size, success, error)`:
    - INSERT into `uploads` table (immutable audit log — even failures are recorded)
    - On success: Check if this file has now been successfully uploaded to **ALL currently active remotes**.
    - `recordings.uploaded` is evaluated against the set of active remotes at the time the completion check is executed. Newly activated remotes do not retroactively invalidate previously completed recordings (`uploaded=true` stays true) unless an explicit reconciliation/backfill mechanism is introduced.
    - If ALL active remotes are complete: UPDATE `recordings SET uploaded=true, uploaded_at=now()` — **Janitor signal only** ("all required remotes are safe")
    - On failure: `uploads` row with `success=false` — `recordings.uploaded` unchanged
- [ ] Implement `silvasonic/uploader/upload_stats.py`:
  - `UploadStats` class — Two-Phase Logging (same pattern as `RecordingStats` and `ControllerStats`):
    - **Startup Phase** (default 5min): Log every upload individually:
      `upload.completed  remote=nextcloud  file=raw_20260329_143000.flac  size_bytes=3200000  duration_s=4.5`
      `upload.failed  remote=nextcloud  file=raw_20260329_143010.flac  error="connection refused"`
    - **Steady State**: Accumulate and emit periodic summary every 5min:
      `upload.summary  interval_uploaded=42  interval_failed=1  interval_bytes=134000000  rate_mb_h=1608.0  total_uploaded=840  total_failed=3  uptime_s=7200`
    - **Shutdown**: `emit_final_summary()` → `upload.final_summary` with lifetime totals
  - Methods: `record_upload(remote_slug, filename, size_bytes, duration_s)`, `record_error(remote_slug, filename, error)`, `record_connection_abort(remote_slug)`, `record_skipped_missing(filename)`, `maybe_emit_summary()`, `emit_final_summary()`
  - Counters: `interval_uploaded/total_uploaded`, `interval_failed/total_failed`, `interval_bytes/total_bytes`, `interval_connection_aborts`, `interval_skipped_missing`
  - No `threading.Lock` needed — Uploader is single-threaded (KISS, unlike Recorder)
  - Phase transition: 1× `upload.startup_phase_complete` log
- [ ] Wire pipeline into `UploaderService.run()`:
  - Poll loop: `find_pending_uploads(remote_slug)` → `encode_wav_to_flac()` → `build_remote_path()` → `upload_file()` → `log_upload_attempt()` → `stats.record_upload()` → cleanup temp FLAC
  - Call `stats.maybe_emit_summary()` after each batch cycle
  - Call `stats.emit_final_summary()` on shutdown
  - Sequential per file (parallel deferred to post-v1.0.0)
  - **Inline schedule check (opt-in):** `_is_within_window(start_hour, end_hour) -> bool` as private method (KISS — 4-line function, no separate module). **Default: both `null` → 24/7 continuous upload.** Users can opt-in to a time window via Web-UI (e.g. start=22, end=6 → upload only at night)
  - **Break on connection error:** If `RcloneResult.is_connection_error` → abort remaining batch, `stats.record_connection_abort()`, wait for next cycle
  - **Missing file handling:** If WAV file does not exist on disk (Janitor deleted it) → `stats.record_skipped_missing()`, skip to next recording
  - `UploaderSettings.enabled` is **NOT checked here** — it is enforced by the Controller in `_evaluate_uploaders()`. If enabled=false, no containers are started at all
  - Respect `UploaderSettings.poll_interval` between cycles
  - Health: `self.health.update_status("upload_engine", True/False, details)`
  - Heartbeat: `get_extra_meta()` → `pending_count`, `uploaded_count`, `failed_count`, `last_upload_at`, `current_remote_slug`

### Acceptance Criteria

> Phase is complete when `just check` passes and all tests below are green.

#### Unit Tests (`services/uploader/tests/unit/test_work_poller.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_finds_pending_for_remote` | Mocked session + remote_slug → correct pending list returned |
| `test_excludes_already_uploaded_to_this_remote` | Recording with successful `uploads` row for this slug → excluded |
| `test_includes_uploaded_to_other_remote` | Recording uploaded to `nextcloud` but not `s3` → included for `s3` |
| `test_excludes_locally_deleted` | `local_deleted=true` → excluded from results |
| `test_batch_size_respected` | Query LIMIT matches parameter |
| `test_empty_result` | No pending recordings → empty list |

#### Unit Tests (`services/uploader/tests/unit/test_flac_encoder.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_encode_creates_flac_file` | Mock subprocess → FLAC path returned |
| `test_encode_returns_correct_path` | Output path: `{stem}.flac` |
| `test_encode_fails_on_ffmpeg_error` | returncode != 0 → raises `FlacEncodingError` |
| `test_encode_cleanup_on_failure` | Partial FLAC removed on error |
| `test_encode_preserves_filename_stem` | Output filename matches input stem |

#### Unit Tests (`services/uploader/tests/unit/test_path_builder.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_builds_correct_remote_path` | `silvasonic/{station_slug}/{sensor}/{YYYY-MM-DD}/{filename}.flac` |
| `test_date_extracted_from_time` | `time=2026-03-29T14:30:00` → `2026-03-29` directory |
| `test_station_name_slugified` | `"Silvasonic Müller-Station [Test]"` → `"silvasonic-mueller-station-test"` |
| `test_station_name_simple` | `"Silvasonic MVP"` → `"silvasonic-mvp"` |
| `test_filename_extension_replaced` | `.wav` input → `.flac` output |

#### Unit Tests (`services/uploader/tests/unit/test_rclone_client.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_generate_rclone_conf_format` | Correct INI format written to temp file |
| `test_generate_rclone_conf_webdav_nextcloud` | Nextcloud `vendor` param set correctly |
| `test_generate_rclone_conf_s3` | S3 access/secret keys in correct INI section |
| `test_upload_success` | Mock subprocess → `RcloneResult(success=True)` |
| `test_upload_failure_file_error` | File-specific error → `RcloneResult(success=False, is_connection_error=False)` |
| `test_upload_failure_connection_error` | Network error → `RcloneResult(success=False, is_connection_error=True)` |
| `test_bandwidth_limit_in_args` | `--bwlimit` present in CLI args |
| `test_checksum_flag_in_args` | `--checksum` present in CLI args |
| `test_upload_timeout` | Subprocess timeout → `RcloneResult(is_connection_error=True)` |

#### Unit Tests (`services/uploader/tests/unit/test_audit_logger.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_success_creates_upload_and_marks_recording` | `success=true` + all active remotes done → `uploads` INSERT + `recordings.uploaded=true` |
| `test_success_partial_remotes` | `success=true` but other active remotes pending → `uploads` INSERT, `recordings.uploaded=false` |
| `test_failure_creates_upload_only` | `success=false` → `uploads` INSERT, `recordings.uploaded` unchanged |
| `test_audit_log_immutable` | INSERT only, no UPDATE on `uploads` table |

#### Unit Tests (`services/uploader/tests/unit/test_upload_stats.py`) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_startup_phase_logs_individually` | During startup (< 5min): `record_upload()` emits `upload.completed` log |
| `test_steady_state_accumulates` | After startup: `record_upload()` does NOT emit individual log |
| `test_summary_emitted_after_interval` | `maybe_emit_summary()` after interval elapsed → `upload.summary` with counters |
| `test_summary_resets_interval_counters` | After summary: interval counters reset to 0, lifetime counters preserved |
| `test_final_summary_on_shutdown` | `emit_final_summary()` → `upload.final_summary` with lifetime totals |
| `test_phase_transition_logged_once` | `upload.startup_phase_complete` emitted exactly once |
| `test_record_error_always_logged` | Errors logged individually regardless of phase |
| `test_connection_abort_counted` | `record_connection_abort()` increments `interval_connection_aborts` |
| `test_skipped_missing_counted` | `record_skipped_missing()` increments `interval_skipped_missing` |

#### Unit Tests (`services/uploader/tests/unit/test_uploader.py` — schedule tests) — `@pytest.mark.unit`

| Test | Validates |
|---|---|
| `test_null_schedule_always_active` | Default: both hours `null` → 24/7 upload (always `True`) |
| `test_within_window` | `_is_within_window(22, 6)`: hour=23 → returns `True` |
| `test_outside_window` | `_is_within_window(22, 6)`: hour=12 → returns `False` |
| `test_overnight_window` | start=22, end=6 → 23:00 inside, 12:00 outside |

#### Integration Tests (`services/uploader/tests/integration/test_flac_encoder_e2e.py`) — `@pytest.mark.integration`

| Test | Validates |
|---|---|
| `test_real_wav_to_flac` | Synthetic WAV (numpy) → ffmpeg → FLAC — file valid |
| `test_flac_smaller_than_wav` | FLAC output is smaller than WAV input |

#### Integration Tests (`services/uploader/tests/integration/test_work_poller_e2e.py`) — `@pytest.mark.integration`

| Test | Validates |
|---|---|
| `test_pending_query_real_db` | Seed `recordings` in Testcontainer DB → correct rows returned for given remote_slug |
| `test_multi_remote_independence` | Seed 1 recording + 1 successful upload for `nextcloud` → `find_pending(slug='nextcloud')` returns empty, `find_pending(slug='s3')` returns the recording |
| `test_uploaded_true_does_not_affect_polling` | Seed recording with `uploaded=true` but no `uploads` row for this slug → still returned as pending |

#### Integration Tests (`services/uploader/tests/integration/test_audit_logger_e2e.py`) — `@pytest.mark.integration`

| Test | Validates |
|---|---|
| `test_upload_success_chain` | Seed recording → log success → `uploads` row + `recordings.uploaded=true` |
| `test_upload_failure_chain` | Seed recording → log failure → `uploads` row, `recordings.uploaded=false` |
| `test_multiple_remotes_tracked` | Same recording, 2 remotes → 2 `uploads` rows |

#### Integration Tests (`services/uploader/tests/integration/test_upload_pipeline_e2e.py`) — `@pytest.mark.integration`

| Test | Validates |
|---|---|
| `test_full_pipeline_mock_rclone` | Seed recordings + workspace → Uploader cycle → FLAC → mock rclone → `uploads` row + `recordings.uploaded=true` |
| `test_pipeline_skips_already_uploaded_to_this_remote` | Recording with successful `uploads` row for this slug → not re-uploaded |
| `test_pipeline_still_uploads_to_other_remote` | Recording uploaded to `nextcloud` (uploads row exists) → pipeline for `s3` still picks it up and uploads |
| `test_pipeline_handles_missing_file` | Recording in DB, file missing → error logged, pipeline continues |
| `test_uploaded_flag_set_as_janitor_signal` | After successful upload to ALL active remotes → `recordings.uploaded=true`, `recordings.uploaded_at` set |
| `test_inactive_remotes_ignored_for_uploaded_flag` | Upload to active remote completes, inactive remote skipped → `recordings.uploaded=true` |

---

## Phase 4: System Tests

**Goal:** Verify Controller correctly manages Uploader containers end-to-end with real Podman. Verify Janitor integration. Equivalent to v0.3.0/v0.5.0 system tests for Recorder/Processor.

**User Stories:** US-U02 (Unbegrenzt weiter aufnehmen), US-U03 (Multi-Target)

**Dependency:** Phase 2 (Controller manages Uploaders) + Phase 3 (Uploader has functional pipeline).

### Source References

> **Read these files before starting Phase 4:**

| Purpose | File |
|---|---|
| Existing system tests — pattern to follow | `tests/system/test_processor_lifecycle.py` |
| Existing resilience tests — pattern to follow | `tests/system/test_processor_resilience.py` |
| System test helpers | `tests/system/_processor_helpers.py` |
| Test-utils shared fixtures | `packages/test-utils/src/silvasonic/test_utils/` |
| Root conftest (Testcontainer setup) | `conftest.py` |
| Integration conftest (DB sessions) | `tests/integration/conftest.py` |

### Tasks

- [ ] Verify Uploader container appears in `podman ps` with correct labels
- [ ] Verify Controller starts Uploaders when `storage_remotes` rows are active
- [ ] Verify Controller stops Uploaders when remote is deactivated
- [ ] Verify Uploader workspace is mounted read-only
- [ ] Verify LogForwarder captures Uploader logs automatically
- [ ] Update Controller `README.md` with Uploader management section

### Acceptance Criteria

> Phase is complete when `just check-all` passes (including image build) and all tests below are green.

#### System Tests (`tests/system/test_uploader_lifecycle.py`) — `@pytest.mark.system`

| Test | Validates |
|---|---|
| `test_uploader_started_for_active_remote` | Seed `storage_remotes` → Controller reconciles → Uploader container running with correct labels |
| `test_uploader_stopped_when_remote_disabled` | Disable remote → Controller reconciles → Uploader stopped and removed |
| `test_uploader_crash_recovery` | Kill Uploader → Controller reconciles → Uploader restarted |
| `test_uploader_readonly_workspace` | Uploader container mounts recorder workspace as `:ro` |

#### System Tests (`tests/system/test_uploader_resilience.py`) — `@pytest.mark.system`

| Test | Validates |
|---|---|
| `test_janitor_respects_uploaded_flag` | `uploaded=true` → Janitor Housekeeping may delete; `uploaded=false` → keeps file |
| `test_uploader_survives_controller_restart` | Kill Controller → Uploader running → new Controller adopts on restart |
| `test_multi_remote_upload_independence` | Seed 2 `storage_remotes` + recordings → Controller starts 2 Uploaders → both upload all recordings independently → `uploads` table has entries for both remotes → `recordings.uploaded=true` ONLY after BOTH successes |

#### Smoke Tests (`tests/smoke/test_health.py`) — `@pytest.mark.smoke`

| Test | Validates |
|---|---|
| `test_uploader_healthy` | Uploader image builds, container starts, `/healthy` → `200` |
| `test_uploader_heartbeat_in_redis` | Uploader heartbeat visible in Redis within 15s |

---

## Phase 5: Documentation & Release

**Goal:** Finalize documentation, bump version, run full pipeline, create release.

**User Stories:** —

**Dependency:** All previous phases complete.

### Tasks

- [ ] Update `VISION.md`: Uploader status → `✅ AS-IS`
- [ ] Update `docs/services/uploader.md`: Status → `implemented`
- [ ] Update Glossary: Uploader → remove `(Planned)` prefix
- [ ] Update `ROADMAP.md`: v0.6.0 → `✅ Done`
- [ ] Update User Stories: mark completed acceptance criteria (US-U01–U03, US-U06 backend)
- [ ] Update this file (`milestone_0_6_0.md`): check all items, Status → `✅ Done`
- [ ] Version bump `0.5.0` → `0.6.0` in 3 files (per `release_checklist.md` §1):
  - `packages/core/src/silvasonic/core/__init__.py`
  - `pyproject.toml` (root)
  - `README.md` Line 5
- [ ] `just check-all` passes (full 12-stage pipeline including Uploader image build)
- [ ] `just test-hw` passes (recommended — no regressions in hardware tests)
- [ ] Commit + annotated tag + push:
  ```bash
  git add -A
  git commit -m "release: v0.6.0 — Uploader (FLAC Compression & Cloud Sync)"
  git tag -a v0.6.0 -m "v0.6.0 — Uploader (FLAC Compression & Cloud Sync)"
  git push origin main
  git push origin v0.6.0
  ```

### Acceptance Criteria

> Phase is complete when `just check-all` and `just test-hw` pass, tag is pushed.

---

## Out of Scope (Deferred)

| Item | Target Version |
|---|---|
| Web-UI for storage remote configuration (US-U04) | v0.8.0 |
| Upload progress in Dashboard (US-U05) | v0.8.0 |
| Upload audit log in Web-UI (US-U06 UI portion) | v0.8.0 |
| `system_services` row for Uploader (no consumer until Web-UI) | v0.8.0 |
| Parallel uploads (multiple files concurrently per instance) | post-v1.0.0 |
| Resume support (partial upload tracking) | post-v1.0.0 |
| Encryption at rest for `storage_remotes.config` | post-v1.0.0 |

> **Note:** US-U04 (Settings via Web-Oberfläche) and US-U05 (Dashboard Status) require the Web-Interface (v0.8.0). This milestone implements the **backend support** — `UploaderSettings` schema, heartbeat payload with upload metrics. Web-Mock routes (`/uploaders`, `/uploaders/{id}`) already exist with hardcoded data. The real UI will be added in v0.8.0.
>
> **Note:** US-U06 (Lückenlose Nachverfolgung) is split: the audit **backend** (immutable `uploads` table, `log_upload_attempt()`) is implemented here. The Web-Interface for browsing the audit log is deferred to v0.8.0.
>
> **Note:** The Uploader only uploads **Raw** recordings as FLAC (ADR-0011 §4: "The Uploader converts `raw` artifacts to FLAC"). Processed (48kHz) files can be regenerated from the lossless FLAC on the cloud side if needed.
