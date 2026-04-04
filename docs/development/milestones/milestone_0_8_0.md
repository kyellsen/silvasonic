# Milestone v0.8.0 — BirdNET (On-device Avian Inference)

> **Target:** v0.8.0 — On-device avian species classification (Worker Pull via DB, ADR-0018)
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0018](../../adr/0018-worker-pull-orchestration.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [BirdNET Stories](../../user_stories/birdnet.md)

---

## Overview

The BirdNET service is an immutable Tier 2 container responsible for performing on-device inference for avian species classification. It processes recorded audio segments and saves detections into the database.

### Key Capabilities

- Pulls unanalyzed `processed` segments via the database (Worker Pull pattern)
- Runs BirdNET TFLite model via native `tflite_runtime` (resident interpreter, no CLI, no birdnetlib)
- Writes detections (`detections` table) and correlates with taxonomy
- Extracts short audio clips per detection and stores them in the BirdNET workspace

### Prerequisites

| Milestone  | Feature                                          |
| ---------- | ------------------------------------------------ |
| **v0.5.0** | Processor (Indexer + Janitor)                    |

### Integration Architecture Decision

> [!IMPORTANT]
> **Native `tflite_runtime` — not `birdnetlib`, not CLI subprocess.**
>
> The BirdNET TFLite model is loaded once at container startup via `tflite_runtime.Interpreter` and remains resident in memory ("warm") for the container's lifetime. This is the BirdNET-Pi approach.
>
> **Rejected alternatives:**
> - **CLI Subprocess:** Massive startup overhead per file (Python boot + TFLite import + model load for every 10s segment). Prevents clean graceful shutdown (must kill subprocess).
> - **`birdnetlib` Wrapper:** Designed for batch-folder processing with internal multiprocessing pools. Incompatible with our single-file Worker Pull pattern (ADR-0018).

### Existing Infrastructure (Reuse — Do NOT Rebuild)

The following structures already exist and MUST be reused or extended in-place:

| Structure | Location | Status | Action for v0.8.0 |
|---|---|---|---|
| `BirdnetSettings` Pydantic schema | `packages/core/src/silvasonic/core/config_schemas.py:82` | Has `confidence_threshold` only | **Extend** with `clip_padding_seconds`, `overlap`, `sensitivity`, `threads` |
| `defaults.yml` (birdnet section) | `services/controller/config/defaults.yml:75-80` | Has `confidence_threshold` only | **Extend** with new fields to match schema |
| `Detection` ORM model | `packages/core/src/silvasonic/core/database/models/detections.py` | Missing `clip_path` column | **Add** `clip_path: Mapped[str \| None]` to match DDL |
| `Recording` ORM model | `packages/core/src/silvasonic/core/database/models/recordings.py` | Complete — has `analysis_state` JSONB | ✅ Reuse as-is (read-only from BirdNET) |
| `Taxonomy` ORM model | `packages/core/src/silvasonic/core/database/models/taxonomy.py` | Complete — PK `(worker, label)` | ✅ Reuse as-is for `common_name` lookup |
| Seeder (`schema_map`) | `services/controller/src/silvasonic/controller/seeder.py:97` | Already maps `"birdnet": BirdnetSettings` | ✅ No change needed (picks up schema extension automatically) |
| Seeder unit tests | `services/controller/tests/unit/test_seeder.py:739-749` | Already tests `BirdnetSettings` in `schema_map` | ✅ No change needed |
| `workspace_dirs.txt` | `scripts/workspace_dirs.txt` | Missing `birdnet` | **Add** `birdnet` entry |
| `_CLEANUP_TABLES` | `tests/integration/conftest.py:21-27` | Missing `detections` | **Add** `detections` before `recordings` (FK order) |
| Existing `BirdnetSettings` unit test | `packages/core/tests/unit/test_service.py:426-429` | Only checks `confidence_threshold` | **Extend** to verify new fields and defaults |
| `ix_recordings_analysis_pending` index | `01-init-schema.sql:119-121` | Complete — partial index on `local_deleted=false` | ✅ Worker Pull query uses this |
| Version refs in docstrings | `config_schemas.py:7`, `defaults.yml:75` | Say "v0.7.0" (wrong) | **Fix** to "v0.8.0" |

---

## Phase 1: Service Scaffold & Database Foundation (Commit 1)

**Goal:** Establish the `birdnet` service container, extend existing core schemas, and prepare DB + workspace.
**User Stories:** Preparation for US-B01, US-B03, US-B04.

### Tasks
- [ ] Scaffold `services/birdnet/` (directories, `pyproject.toml`, `.env` mapping).
- [ ] **Extend** existing `BirdnetSettings` in `packages/core/src/silvasonic/core/config_schemas.py` with new fields (`clip_padding_seconds: float = 3.0`, `overlap: float = 0.0`, `sensitivity: float = 1.0`, `threads: int = 1`). Fix version comment from "v0.7.0" to "v0.8.0".
- [ ] **Extend** existing `birdnet` section in `services/controller/config/defaults.yml` to match the updated schema. Fix version comment from "v0.7.0" to "v0.8.0".
- [ ] **Add** `clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)` to the existing `Detection` model in `packages/core/src/silvasonic/core/database/models/detections.py` to match the DDL.
- [ ] **Add** `birdnet` entry to `scripts/workspace_dirs.txt`.
- [ ] Create `Containerfile` including `tflite-runtime`, `soundfile`, `numpy`.
- [ ] Initialize `SilvaService` base class — reuse `Recording` and `Detection` models from `silvasonic.core.database.models` (do NOT create new models).
- [ ] Read `system_config` on startup for `BirdnetSettings`, `SystemSettings` (latitude, longitude) — use `SystemConfig` model from `silvasonic.core.database.models.system`.

### Testing (Phase 1)
- [ ] **`unit`** — `packages/core/tests/unit/test_service.py`: **Extend** existing `test_birdnet_settings_defaults` to verify all new fields (`clip_padding_seconds=3.0`, `overlap=0.0`, `sensitivity=1.0`, `threads=1`). Add boundary validation tests.
- [ ] **`unit`** — `packages/core/tests/unit/test_recording_model.py`: Verify existing `analysis_state` tests still pass after any model changes.
- [ ] **`smoke`** — `tests/smoke/conftest.py` + `test_health.py`: Add `birdnet_container` fixture and `test_birdnet_healthy` smoke test (health endpoint returns 200).

---

## Phase 2: Inference Loop & Worker Pull Orchestration (Commit 2)

**Goal:** Implement the asynchronous analysis loop that pulls segments and generates detections.
**User Stories:** US-B01 (Automatic detection), US-B03 (Location logic), US-B04 (Confidence threshold).

### Tasks
- [ ] Implement Worker Pull pattern (`SELECT ... FOR UPDATE SKIP LOCKED` on `recordings`) using the existing `ix_recordings_analysis_pending` partial index. Update `recordings.analysis_state` JSONB with `{"birdnet": "done"}` after processing.
- [ ] Load BirdNET TFLite model once at service startup via `tflite_runtime.Interpreter` (resident, warm). Split processed WAV files into 3-second chunks using `soundfile`/`numpy`. Run inference per chunk through the resident interpreter.
- [ ] Map DB runtime config (latitude, longitude from `SystemSettings`; `min_conf`, `sensitivity`, `overlap` from `BirdnetSettings`) to inference parameters. Derive `week` automatically from `recordings.time` (`isocalendar().week`).
- [ ] Calculate absolute detection timestamps from `recordings.time` + detection offset.
- [ ] Implement explicit memory management: `del audio_chunk` after each inference, periodic `gc.collect()` to prevent leaks in long-running loops.
- [ ] Implement graceful shutdown: check `shutdown_event.is_set()` between inference chunks to allow clean exit without aborting mid-inference.
- [ ] Save results using the existing `Detection` ORM model — set `worker='birdnet'`, look up `common_name` from `Taxonomy` table via `(worker='birdnet', label)` PK.

### Testing (Phase 2)
- [ ] **`unit`** — `services/birdnet/tests/unit/test_inference.py`: Test audio chunking logic (3-second splitting, overlap handling), timestamp offset calculation (`recording.time + start_offset → absolute time`), and result-to-detection mapping. Mock `tflite_runtime.Interpreter`.
- [ ] **`unit`** — `services/birdnet/tests/unit/test_worker.py`: Test graceful shutdown logic (`shutdown_event.is_set()` between chunks stops processing). Test that `analysis_state` JSONB is updated correctly (key `"birdnet"` set to `"done"`).
- [ ] **`integration`** — `services/birdnet/tests/integration/test_worker_pull.py`: Using `testcontainers` (PostgreSQL), test the full Worker Pull cycle: insert test recordings → claim via `FOR UPDATE SKIP LOCKED` → verify `detections` rows have correct `recording_id`, `time`, `end_time`, `worker='birdnet'`, `label`, `confidence`. Verify `analysis_state` is updated.
- [ ] **`integration`** — `services/birdnet/tests/integration/conftest.py`: Create service-specific conftest with `_CLEANUP_TABLES = ("detections", "recordings", "devices", "system_config")` in FK-safe order (per `testing.md` §10).

---

## Phase 3: Audio Clip Extraction (Commit 3)

**Goal:** Extract and persist short audio clips for each detection.
**User Stories:** US-B01 (clip storage), US-B02 (playback preparation).

### Tasks
- [ ] Implement clip extraction using `soundfile`: read detection time range ± `clip_padding_seconds` (from `BirdnetSettings`) from the processed WAV file, write to `birdnet/clips/`.
- [ ] Clip naming convention: `{recording_id}_{start_ms}_{end_ms}_{label}.wav`. Store the relative path (`clips/...`) in `detections.clip_path` via the `Detection` ORM model.
- [ ] Ensure `birdnet/clips/` directory is created at service startup.
- [ ] Handle edge cases: detection at file start/end (clamp padding to file boundaries), silent/corrupt files (skip gracefully, log warning).

### Testing (Phase 3)
- [ ] **`unit`** — `services/birdnet/tests/unit/test_clip_extraction.py`: Test clip filename generation (`{recording_id}_{start_ms}_{end_ms}_{label}.wav`), path construction, label sanitization (remove unsafe filesystem characters), padding clamping at file boundaries (start < 0 → 0, end > duration → duration).
- [ ] **`integration`** — `services/birdnet/tests/integration/test_clip_pipeline.py`: Using `testcontainers` (PostgreSQL) + a test WAV fixture file on `/tmp`, run the full clip extraction pipeline: recording → inference mock → clip extraction → verify `detections.clip_path` is set in DB → verify clip file exists at the expected path with correct duration.

---

## Phase 4: Service Status & Lifecycle Integration (Commit 4)

**Goal:** Integrate BirdNET fully into the Silvasonic ecosystem (Controller, Heartbeats).
**User Stories:** US-B05 (Analysis status via Heartbeat), US-B06 (Enable/Disable via DB/Controller).

### Tasks
- [ ] Implement Heartbeat publisher pushing current state ("active", "waiting", backlogs) to Redis — reuse `Heartbeat` class from `silvasonic.core.heartbeat`.
- [ ] Update Controller's Seeder to include `birdnet` in `system_services` table (enabled by default) — add seed row to `ServiceSeeder` if one exists, or add to `run_all_seeders()`.
- [ ] Ensure clean graceful shutdown logic in BirdNET to safely abort/finish active inferences on `SIGTERM`.
- [ ] Add basic routes to `services/web-mock` to verify detection data (US-B02 preparation).

### Testing (Phase 4)
- [ ] **`unit`** — `services/birdnet/tests/unit/test_heartbeat.py`: Test heartbeat payload structure (contains `service`, `instance_id`, `health.status`, `meta.backlogs`, `meta.state`).
- [ ] **`system`** — `tests/system/test_birdnet_lifecycle.py`: Using real Podman with isolated network, test: Controller starts BirdNET container → BirdNET publishes heartbeat to Redis → Controller stops BirdNET via SIGTERM → BirdNET exits cleanly (return code 0).
- [ ] **`system`** — `tests/system/test_birdnet_lifecycle.py`: Test enable/disable: set `birdnet` in `system_services` to `enabled=false` → Controller stops BirdNET → set to `enabled=true` → Controller restarts BirdNET → heartbeat reappears in Redis.
- [ ] **`smoke`** — `tests/smoke/test_health.py`: Extend with `test_birdnet_heartbeat_in_redis` (verify heartbeat payload contains `service=birdnet`, `health.status=ok`, `meta.state` field).

---

## Phase 5: Final System Audit & Documentation (Commit 5)

**Goal:** Polish the system, verify system behavior, and finalize docs.
**User Stories:** All US-Bxx verified.

### Tasks
- [ ] Verify `check-all` passes (lint, mypy, all tests up to smoke/system).
- [ ] Create `services/birdnet/README.md` using `services/_template_readme.md` boilerplate and convert `docs/services/birdnet.md` to a link-stub (per `STRUCTURE.md` §4).
- [ ] **Add** `"detections"` to `_CLEANUP_TABLES` in `tests/integration/conftest.py` — insert before `"recordings"` (FK-safe order, mandatory per `testing.md` §10).

### Testing (Phase 5)
- [ ] **`system`** — `tests/system/test_birdnet_pipeline.py`: Full pipeline integration: Recorder produces WAV → Indexer registers in `recordings` → BirdNET claims, analyzes, writes `detections` + clips → verify end-to-end data flow. Ensure no OOM or resource conflicts (BirdNET: `oom_score_adj=+500`, Recorder: `-999`).
- [ ] **E2E:** Deferred to v0.9.0 (Web-Interface required).

---

## Phase 6: Version Bump & Release v0.8.0 (Commit 6)

**Goal:** Formalize the release strictly according to `release_checklist.md`.

### Tasks
- [ ] Ensure branch is clean and `just check-all` finishes successfully.
- [ ] Update `__version__` in `packages/core/src/silvasonic/core/__init__.py`.
- [ ] Update version in the root `pyproject.toml` (Do **NOT** update service pyproject.toml files).
- [ ] Update version status in `ROADMAP.md` and the root `README.md`.
- [ ] Run `uv lock` to synchronize the lockfile.
- [ ] Create annotated Git tag `v0.8.0` (`git tag -a v0.8.0 -m "v0.8.0 — BirdNET"`) and push to upstream.

---

## Out of Scope (Deferred)

| Item                   | Target Version |
| ---------------------- | -------------- |
| Real Web-Interface UI  | v0.9.0         |
| Push-based Orchestration| Rejected (ADR-0018) |
| E2E tests (Playwright) | v0.9.0 (requires Web-Interface) |
| Janitor: Clip cleanup when recordings are deleted | Follow-up ([Issue](../issues/008-clip-cleanup-janitor.md)) |
