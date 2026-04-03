# Milestone v0.6.0 — Processor Cloud Sync (Upload Worker)

> **Target:** v0.6.0 — Single-target cloud sync as internal Processor worker: FLAC compression, Rclone-based upload, Janitor integration, Audit logging
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0009](../../adr/0009-zero-trust-data-sharing.md), [ADR-0011](../../adr/0011-audio-recording-strategy.md), [ADR-0018](../../adr/0018-worker-pull-orchestration.md), [ADR-0019](../../adr/0019-unified-service-infrastructure.md), [ADR-0023](../../adr/0023-configuration-management.md), [ADR-0024](../../adr/0024-ffmpeg-audio-engine.md), [Refactoring Plan](#), [Processor Service](../../services/processor.md), [Testing Guidelines](../testing.md), [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [Glossary](../../glossary.md)
>
> **User Stories:** [US-U01](../../user_stories/cloud_sync.md#us-u01), [US-U02](../../user_stories/cloud_sync.md#us-u02), [US-U04](../../user_stories/cloud_sync.md#us-u04), [US-U06](../../user_stories/cloud_sync.md#us-u06)

---

## Architecture Overview

The Cloud-Sync-Worker is an **internal async worker within the Processor** (Tier 1), following the same pattern as the Indexer and Janitor. It is **NOT** a standalone Tier 2 container — there is no Controller management, no multi-instance orchestration, and no separate health port.

This is a KISS simplification of the original multi-target Uploader architecture (archived, see ADR-0009 NOTE).

### Key Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where does upload run? | **Inside Processor** as async worker | Same pattern as Indexer/Janitor; no Controller complexity |
| How many targets? | **Single target** configured via `system_config` key `"cloud_sync"` | KISS: Multi-target adds orchestration complexity with no MVP value |
| Config source? | **`CloudSyncSettings`** in `system_config` JSONB | No `storage_remotes` table needed; same Pydantic schema pattern as other settings. Remote target via `remote_type` + `remote_config` dict |
| Upload tracking? | **`recordings.uploaded` boolean** | Simple Janitor signal; one target = one boolean |
| Audit log? | **`uploads` table** (immutable, no `remote_slug` FK) | Keep audit trail for debugging; simplified without multi-target references |
| FLAC encoding? | **`ffmpeg`** subprocess (ADR-0024) | Same tool as Recorder; lossless, ~50% size reduction |
| Upload backend? | **`rclone`** subprocess | Universal protocol support (WebDAV/Nextcloud, S3, SFTP) without Python library dependencies |
| Default state? | **`enabled: false`** | Prevents Janitor deadlock when no rclone target is configured |
| Credentials? | **Fernet-encrypted in `system_config` JSONB** | Sensitive values (user, pass) AES-encrypted via `SILVASONIC_ENCRYPTION_KEY` (.env); `enc:` prefix detection for graceful plaintext fallback |

### Remote Path Convention

```
silvasonic/{station_slug}/{sensor_id}/{YYYY-MM-DD}/{filename}.flac
```

**Example:**
```
Local:   /workspace/recorder/ultramic-01/data/raw/raw_20260329_143000.wav
Remote:  silvasonic/silvasonic-dev/ultramic-01/2026-03-29/raw_20260329_143000.flac
```

The `path_builder` module is the **only component** that knows about the remote directory convention.

---

## Phase 1: Core Infrastructure

**Goal:** Build the foundation for credential encryption and cloud sync configuration. Add the `crypto` module to core, extend the DB schema, install rclone in the Processor container, and implement the `CloudSyncSeeder` in the Controller.

**User Stories:** US-U06 (Seamless tracking — audit log schema)

**Dependency:** Preparatory refactoring (v0.5.x) must be complete — `storage_remotes` table removed, `CloudSyncSettings.enabled` defaults to `false`, `remote_type` / `remote_config` fields present in schema.

> **Cross-Cutting Dependency (core):** Credential encryption uses `packages/core/src/silvasonic/core/crypto.py` — a thin Fernet wrapper (`encrypt_value`, `decrypt_value`) added to `silvasonic-core` as part of this milestone. The encryption key lives in `.env` as `SILVASONIC_ENCRYPTION_KEY`.

### Source References

> **Read these files before starting Phase 1:**

| Purpose | File |
|---------|------|
| Upload DB model | `packages/core/src/silvasonic/core/database/models/system.py` |
| CloudSyncSettings schema | `packages/core/src/silvasonic/core/config_schemas.py` |
| Database DDL | `services/database/init/01-init-schema.sql` |
| Existing Controller seeder pattern | `services/controller/src/silvasonic/controller/seeder.py` |
| Environment config | `.env` / `.env.example` |

### Tasks

- [ ] Update Database Schema & Models:
  - Add `remote_path TEXT` column to `uploads` table in `01-init-schema.sql`
  - Add `CREATE INDEX ix_uploads_attempt_at ON uploads (attempt_at DESC)` in `01-init-schema.sql`
  - Add `remote_path: Mapped[str | None]` to `Upload` model in `packages/core/src/silvasonic/core/database/models/system.py`
- [ ] Add `rclone` to Processor `Containerfile` system dependencies (alongside existing `ffmpeg`)
- [ ] Implement `packages/core/src/silvasonic/core/crypto.py`:
  - `encrypt_value(plaintext: str, key: bytes) -> str` — Fernet encrypt, returns `enc:<token>` prefixed string
  - `decrypt_value(value: str, key: bytes) -> str` — if `enc:` prefix → decrypt; otherwise return as-is (plaintext fallback)
  - `load_encryption_key() -> bytes` — read `SILVASONIC_ENCRYPTION_KEY` from env, raise clear error if missing
  - Key generation helper: `python -m silvasonic.core.crypto generate-key` (prints new Fernet key to stdout)
- [ ] Add `cryptography>=43.0` to `packages/core/pyproject.toml` dependencies
- [ ] Add `SILVASONIC_ENCRYPTION_KEY` to `.env` and `.env.example` with generated Fernet key
- [ ] Implement `CloudSyncSeeder` in `services/controller/src/silvasonic/controller/seeder.py`:
  - Reads 4 optional env vars: `SILVASONIC_CLOUD_REMOTE_TYPE`, `_URL`, `_USER`, `_PASS`
  - **All-or-nothing:** if any of the 4 is missing → log debug + skip (cloud sync stays as seeded by defaults.yml)
  - If all 4 present: build `remote_config` dict, encrypt `user` and `pass` via `crypto.encrypt_value()`
  - **UPSERT** (not `ON CONFLICT DO NOTHING`): `.env` is infrastructure, always overwrites DB values
  - Sets `cloud_sync.enabled = true`, `cloud_sync.remote_type`, `cloud_sync.remote_config` in `system_config`
  - For `remote_type=webdav`: auto-set `vendor=nextcloud` if URL contains `nextcloud` or ends with `/webdav/`
  - Requires `SILVASONIC_ENCRYPTION_KEY` — if missing while credentials are set → clear error + skip
  - Wired into `run_all_seeders()` after `ConfigSeeder` (so defaults exist first), before `AuthSeeder`

### Acceptance Criteria

> Phase is complete when `just check` passes and all tests below are green.

#### Unit Tests (`packages/core/tests/unit/test_crypto.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|----------|
| `test_encrypt_decrypt_roundtrip` | `decrypt_value(encrypt_value(s, k), k) == s` |
| `test_plaintext_fallback` | No `enc:` prefix → returned as-is |
| `test_decrypt_wrong_key_fails` | Wrong key → `InvalidToken` raised |
| `test_load_encryption_key_missing` | Env var not set → clear error message |
| `test_generate_key_valid_fernet` | Generated key is valid Fernet key |

#### Unit Tests (`services/controller/tests/unit/test_cloud_sync_seeder.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|----------|
| `test_all_env_vars_set_seeds_encrypted` | All 4 vars → `system_config` updated with `enc:` values, `enabled=true` |
| `test_partial_env_vars_skips` | Only 2 of 4 vars → no DB change, debug log |
| `test_no_env_vars_skips` | No vars → no DB change, no error |
| `test_upsert_overwrites_existing` | Existing `cloud_sync` in DB → overwritten with new `.env` values |
| `test_missing_encryption_key_errors` | Credentials set but no `SILVASONIC_ENCRYPTION_KEY` → clear error, skip |
| `test_webdav_auto_vendor_nextcloud` | `remote_type=webdav` + URL with `/webdav/` → `vendor=nextcloud` auto-set |

---

## Phase 2: Upload Worker Modules

**Goal:** Implement all Cloud-Sync-Worker modules within the Processor service. The worker polls for pending recordings, compresses WAV→FLAC, uploads via rclone, logs the attempt, and updates the database.

**User Stories:** US-U01 (Automatic cloud upload with FLAC), US-U06 (Seamless tracking)

**Dependency:** Phase 1 (Core Infrastructure) must be complete — crypto module available, DB schema updated, rclone installed in container.

### Modules

| Module | File | Responsibility |
|--------|------|----------------|
| **Upload Worker** | `upload_worker.py` | Main async loop: poll → encode → upload → audit → stats |
| **Work Poller** | `work_poller.py` | Find recordings with `uploaded=false` and `local_deleted=false` |
| **FLAC Encoder** | `flac_encoder.py` | WAV→FLAC via ffmpeg subprocess |
| **Path Builder** | `path_builder.py` | Build remote path from DB fields |
| **Rclone Client** | `rclone_client.py` | Upload files via rclone subprocess |
| **Audit Logger** | `audit_logger.py` | Immutable `uploads` table + set `recordings.uploaded=true` |
| **Upload Stats** | `upload_stats.py` | Two-Phase Logging: startup detail → periodic summary |

### Source References

> **Read these files before starting Phase 2:**

| Purpose | File |
|---------|------|
| Processor service entry point | `services/processor/src/silvasonic/processor/__main__.py` |
| Indexer — internal worker pattern to copy | `services/processor/src/silvasonic/processor/indexer.py` |
| Janitor — internal worker pattern reference | `services/processor/src/silvasonic/processor/janitor.py` |
| RecordingStats — Two-Phase Logging pattern | `services/recorder/src/silvasonic/recorder/recording_stats.py` |
| Recording DB model | `packages/core/src/silvasonic/core/database/models/recordings.py` |
| Crypto module (Phase 1) | `packages/core/src/silvasonic/core/crypto.py` |
| FFmpeg usage pattern (ADR-0024) | `docs/adr/0024-ffmpeg-audio-engine.md` |
| Worker Pull orchestration (ADR-0018) | `docs/adr/0018-worker-pull-orchestration.md` |

### Tasks

- [ ] Implement `upload_worker.py`:
  - `UploadWorker(session_factory, settings, stats)` — main async loop
  - Early exit: if `CloudSyncSettings.enabled == false` → log and skip (global pause)
  - Early exit: if `CloudSyncSettings.remote_type is None` → log warning and skip (no target configured)
  - Poll loop: `find_pending()` → encode → upload → audit → repeat
  - Sequential per file (parallel deferred to post-v1.0.0)
  - Inline schedule check (opt-in): `_is_within_window(start_hour, end_hour) -> bool` (KISS — 4-line function). Default: both `null` → 24/7 continuous upload
  - Break on connection error: abort remaining batch, wait for next cycle
  - Missing file handling: if WAV file not on disk (Janitor deleted it) → log, skip to next
  - Respect `CloudSyncSettings.poll_interval` between cycles
  - Health: `self.health.update_status("upload_worker", True/False, details)`
  - Heartbeat extra meta: `pending_count`, `uploaded_count`, `failed_count`, `last_upload_at`
- [ ] Implement `work_poller.py`:
  - `find_pending_uploads(session, batch_size) -> list[PendingUpload]`
  - Single-target query: `WHERE uploaded=false AND local_deleted=false ORDER BY time ASC LIMIT batch`
  - Uses `ix_recordings_upload_pending` partial index on `recordings`
  - `PendingUpload` Pydantic model: `recording_id, file_raw, sensor_id, time`
- [ ] Implement `flac_encoder.py`:
  - `encode_wav_to_flac(wav_path: Path, output_dir: Path) -> Path`
  - ffmpeg subprocess: `ffmpeg -i input.wav -c:a flac -compression_level 5 output.flac`
  - Validate output file (exists, non-zero size)
  - Clean up partial FLAC file on failure
  - No FLAC caching — re-encode on retry (encoding is <1s per segment on RPi 5)
- [ ] Implement `path_builder.py`:
  - `build_remote_path(station_name, sensor_id, time, filename) -> str`
  - Convention: `silvasonic/{station_slug}/{sensor_id}/{YYYY-MM-DD}/{filename}.flac`
  - Station name slugified via simple inline regex (no external dependency)
- [ ] Implement `rclone_client.py`:
  - `RcloneClient(cloud_sync_settings: CloudSyncSettings, encryption_key: bytes)`:
    - `generate_rclone_conf() -> Path` — decrypt `enc:`-prefixed values in `remote_config` via `crypto.decrypt_value()`, then write temp `rclone.conf`
    - Validate `remote_config` via `schemas.cloud_sync.validate_rclone_config(remote_type, remote_config)` on init (validates after decryption)
    - For WebDAV/Nextcloud: set `vendor = nextcloud`
    - `upload_file(local, remote_path, bandwidth_limit) -> RcloneResult`
    - `RcloneResult(success, bytes_transferred, error_message, duration_s, is_connection_error)`
    - Bandwidth limiting via `--bwlimit` from `CloudSyncSettings.bandwidth_limit`
    - Checksum verification via `--checksum` flag
- [ ] Implement `audit_logger.py`:
  - `log_upload_attempt(session, recording_id, filename, remote_path, size, success, error_message)`:
    - INSERT into `uploads` table (immutable audit log)
    - Pass `duration_s` as JSON within `error_message` if needed for detailed metrics (KISS)
    - On success: UPDATE `recordings SET uploaded=true, uploaded_at=now()` — Janitor signal
    - On failure: `uploads` row with `success=false`, `recordings.uploaded` unchanged
- [ ] Implement `upload_stats.py`:
  - `UploadStats` — Two-Phase Logging (same pattern as `RecordingStats`):
    - **Startup Phase** (default 5min): log every upload individually
    - **Steady State**: periodic summary every 5min
    - **Shutdown**: `emit_final_summary()` with lifetime totals
  - No `threading.Lock` needed — single-threaded worker
- [ ] Wire `UploadWorker` into `ProcessorService.__main__.py`:
  - Start alongside Indexer and Janitor as third internal worker
  - Shutdown: `emit_final_summary()` on SIGTERM

### Acceptance Criteria

> Phase is complete when `just check` passes and all tests below are green.

#### Unit Tests (`services/processor/tests/unit/test_upload_worker.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_upload_disabled_skips` | `enabled=false` → worker does not poll |
| `test_poll_loop_processes_pending` | Mocked pending list → encode → upload → audit called in sequence |
| `test_connection_error_aborts_batch` | `is_connection_error=True` → remaining batch skipped |
| `test_missing_file_skipped` | WAV not on disk → logged, next recording processed |
| `test_null_schedule_always_active` | Both hours `null` → 24/7 upload |
| `test_within_window` | `_is_within_window(22, 6)`: hour=23 → `True` |
| `test_outside_window` | `_is_within_window(22, 6)`: hour=12 → `False` |

#### Unit Tests (`services/processor/tests/unit/test_work_poller.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_finds_pending_recordings` | `uploaded=false, local_deleted=false` → returned |
| `test_excludes_already_uploaded` | `uploaded=true` → excluded |
| `test_excludes_locally_deleted` | `local_deleted=true` → excluded |
| `test_batch_size_respected` | LIMIT matches parameter |
| `test_empty_result` | No pending recordings → empty list |

#### Unit Tests (`services/processor/tests/unit/test_flac_encoder.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_encode_creates_flac_file` | Mock subprocess → FLAC path returned |
| `test_encode_fails_on_ffmpeg_error` | returncode != 0 → raises `FlacEncodingError` |
| `test_encode_cleanup_on_failure` | Partial FLAC removed on error |

#### Unit Tests (`services/processor/tests/unit/test_path_builder.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_builds_correct_remote_path` | `silvasonic/{slug}/{sensor}/{date}/{filename}.flac` |
| `test_station_name_slugified` | `"Silvasonic Müller-Station"` → `"silvasonic-mueller-station"` |
| `test_filename_extension_replaced` | `.wav` input → `.flac` output |

#### Unit Tests (`services/processor/tests/unit/test_rclone_client.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_generate_rclone_conf_format` | Correct INI format written |
| `test_upload_success` | Mock subprocess → `RcloneResult(success=True)` |
| `test_upload_failure_connection` | Network error → `is_connection_error=True` |
| `test_bandwidth_limit_in_args` | `--bwlimit` present in CLI args |
| `test_encrypted_credentials_decrypted` | `enc:`-prefixed values in `remote_config` → plaintext in generated `rclone.conf` |

#### Unit Tests (`services/processor/tests/unit/test_audit_logger.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_success_marks_uploaded` | `success=true` → `uploads` INSERT + `recordings.uploaded=true` |
| `test_failure_no_flag_change` | `success=false` → `uploads` INSERT, `recordings.uploaded` unchanged |
| `test_audit_log_immutable` | INSERT only, no UPDATE on `uploads` table |

#### Unit Tests (`services/processor/tests/unit/test_upload_stats.py`) — `@pytest.mark.unit`

| Test | Validates |
|------|-----------|
| `test_startup_phase_logs_individually` | During startup: individual `upload.completed` log |
| `test_steady_state_accumulates` | After startup: no individual log |
| `test_summary_emitted_after_interval` | `maybe_emit_summary()` → `upload.summary` |
| `test_final_summary_on_shutdown` | `emit_final_summary()` → lifetime totals |

#### Integration Tests (`services/processor/tests/integration/test_upload_pipeline_e2e.py`) — `@pytest.mark.integration`

| Test | Validates |
|------|-----------|
| `test_full_pipeline_mock_rclone` | Seed recordings + workspace → poll → FLAC → mock rclone → audit → `uploaded=true` |
| `test_pipeline_skips_already_uploaded` | `uploaded=true` recording → not re-processed |
| `test_pipeline_handles_missing_file` | Recording in DB, file missing → error logged, pipeline continues |

#### Integration Tests (`services/processor/tests/integration/test_flac_encoder_e2e.py`) — `@pytest.mark.integration`

| Test | Validates |
|------|-----------|
| `test_real_wav_to_flac` | Synthetic WAV (numpy) → ffmpeg → valid FLAC file |
| `test_flac_smaller_than_wav` | FLAC output is smaller than WAV input |

---

## Phase 3: System Tests

**Goal:** Verify upload worker runs correctly within the full Processor container. Verify Janitor integration with upload status.

**User Stories:** US-U02 (Continue recording indefinitely)

**Dependency:** Phase 2 (upload worker modules implemented and unit-tested).

### Tasks

- [ ] Verify upload worker starts alongside Indexer and Janitor in Processor container
- [ ] Verify `CloudSyncSettings.enabled=false` → upload worker inactive (no rclone calls)
- [ ] Verify Janitor respects `uploaded` flag for retention decisions
- [ ] Update Processor `README.md` with Cloud-Sync-Worker section

### Acceptance Criteria

> Phase is complete when `just check-all` passes (including Processor image build).

#### System Tests (`tests/system/test_processor_lifecycle.py`) — `@pytest.mark.system`

| Test | Validates |
|------|-----------|
| `test_upload_worker_starts_with_processor` | Processor container logs show upload worker initialization |
| `test_upload_disabled_no_rclone` | `enabled=false` → no rclone subprocess spawned |

#### System Tests (`tests/system/test_processor_resilience.py`) — `@pytest.mark.system`

| Test | Validates |
|------|-----------|
| `test_janitor_respects_uploaded_flag` | `uploaded=true` → Janitor may delete; `uploaded=false` → keeps file |

---

## Phase 4: Documentation & Release

**Goal:** Finalize documentation, bump version, run full pipeline, create release.

**Dependency:** All previous phases (1–3) complete.

### Tasks

- [ ] Update `VISION.md`: Processor status annotation (Cloud-Sync-Worker → `✅ AS-IS`)
- [ ] Update `ROADMAP.md`: v0.6.0 → `✅ Done`
- [ ] Update User Stories: mark completed acceptance criteria (US-U01, US-U02, US-U06 backend)
- [ ] Update Processor `README.md`: Implementation Status table
- [ ] Update this file (`milestone_0_6_0.md`): check all items, Status → `✅ Done`
- [ ] Version bump `0.5.x` → `0.6.0` in 3 files (per `release_checklist.md` §1):
  - `packages/core/src/silvasonic/core/__init__.py`
  - `pyproject.toml` (root)
  - `README.md` Line 5
- [ ] `just check-all` passes (full pipeline including Processor image rebuild with rclone)
- [ ] `just test-hw` passes (recommended — no regressions)
- [ ] Commit + annotated tag + push:
  ```bash
  git add -A
  git commit -m "release: v0.6.0 — Processor Cloud Sync (Upload Worker)"
  git tag -a v0.6.0 -m "v0.6.0 — Processor Cloud Sync (Upload Worker)"
  git push origin main
  git push origin v0.6.0
  ```

---

## Out of Scope (Deferred)

| Item | Target Version |
|------|----------------|
| Web-UI for remote target configuration (US-U04) | v0.9.0 |
| Upload progress in Dashboard (US-U05) | v0.9.0 |
| Upload audit log in Web-UI (US-U06 UI portion) | v0.9.0 |
| Parallel uploads (multiple files concurrently) | post-v1.0.0 |
| Resume support (partial upload tracking) | post-v1.0.0 |
| Multi-target upload | post-v1.0.0 |
| Hardware-backed KMS / Secure Element integration | post-v1.0.0 |

> **Note:** US-U04 (Settings via Web UI) and US-U05 (Dashboard Status) require the Web-Interface (v0.9.0). This milestone implements the **backend support** — `CloudSyncSettings` schema, heartbeat payload with upload metrics. Web-Mock routes (`/upload`) already exist with mock data.
>
> **Note:** US-U06 (Seamless tracking) is split: the audit **backend** (immutable `uploads` table) is implemented here. The Web-Interface for browsing the audit log is deferred to v0.9.0.
>
> **Note:** The upload worker only uploads **Raw** recordings as FLAC (ADR-0011 §4). Processed (48kHz) files can be regenerated from the lossless FLAC on the cloud side if needed.
