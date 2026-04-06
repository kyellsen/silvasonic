# Milestone v0.8.0 — BirdNET (On-device Avian Inference)

> **Target:** v0.8.0 — On-device avian species classification (Worker Pull via DB, ADR-0018)
> **Status:** 🔨 In Progress
>
> **References:** [ADR-0018](../../adr/0018-worker-pull-orchestration.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [BirdNET Stories](../../user_stories/birdnet.md)

---

## Overview

The BirdNET service is an immutable Tier 2 container responsible for performing on-device inference for avian species classification. It processes recorded audio segments and saves detections into the database.

### Key Capabilities

- Pulls unanalyzed `processed` segments via the database (Worker Pull pattern)
- Runs BirdNET inference to generate classifications
- Writes detections (`detections` table) using the raw English labels provided by the model
- Extracts short audio clips per detection and stores them in the BirdNET workspace

### Prerequisites

| Milestone  | Feature                                          |
| ---------- | ------------------------------------------------ |
| **v0.5.0** | Processor (Indexer + Janitor)                    |

### Architecture Decision: Completed ✅

> [!NOTE]
> **Spike complete.** Native `ai-edge-litert` is the chosen inference engine on pure Python 3.13.
> See [ADR-0027](../../adr/0027-birdnet-inference-engine.md).

#### Key Findings (Spike v3)
- **Native is ~35% faster** per 10s segment (155 ms avg vs 238 ms)
- **Initialization:** Native has much lower measured initialization overhead.
- **Memory Footprint:** Native stays flat at ~201 MB RSS. `birdnetlib` exhibits higher RSS growth across sequential runs.
- **Identical results:** Native produces identical outputs on the evaluated fixtures.
- **Container:** `python:3.13-slim-bookworm` (standardized baseline, `ai-edge-litert` provides cp313 wheels)
- **Custom code surface:** ~60 lines (sigmoid, labels, meta-model, windowing, numpy mask filtering)


### Existing Infrastructure (Reuse — Do NOT Rebuild)

The following structures already exist and MUST be reused or extended in-place:

| Structure | Location | Status | Action for v0.8.0 |
|---|---|---|---|
| `BirdnetSettings` Pydantic schema | `packages/core/src/silvasonic/core/config_schemas.py:82` | Has `confidence_threshold` only | **Extend** with `clip_padding_seconds`, `overlap`, `sensitivity`, `threads`, `processing_order` (lifecycle toggle `enabled` is in `managed_services`, NOT here) |
| `defaults.yml` (birdnet section) | `services/controller/config/defaults.yml:75-80` | Has `confidence_threshold` only | **Extend** with new fields to match schema |
| `Detection` ORM model | `packages/core/src/silvasonic/core/database/models/detections.py` | Missing `clip_path` column | **Add** `clip_path: Mapped[str \| None]` to match DDL |
| `Recording` ORM model | `packages/core/src/silvasonic/core/database/models/recordings.py` | Complete — has `analysis_state` JSONB | ✅ Reuse as-is (read-only from BirdNET) |
| Seeder (`schema_map`) | `services/controller/src/silvasonic/controller/seeder.py:97` | Already maps `"birdnet": BirdnetSettings` | ✅ No change needed (picks up schema extension automatically) |
| `workspace_dirs.txt` | `scripts/workspace_dirs.txt` | Missing `birdnet` | **Add** `birdnet` entry |
| `_CLEANUP_TABLES` | `tests/integration/conftest.py` | Removed | **Replaced** with dynamic `clean_database` from `test-utils` |
| Existing `BirdnetSettings` unit test | `packages/core/tests/unit/test_service.py:426-429` | Only checks `confidence_threshold` | **Extend** to verify new fields and defaults |
| `ix_recordings_analysis_pending` index | `01-init-schema.sql:119-121` | Complete — partial index on `local_deleted=false` | ✅ Worker Pull query uses this |
| Global Test Fixtures | `tests/fixtures/audio/` | Three files (Robin, Blackbird, Sparrow) pre-processed to exact 10s, 48kHz mono | ✅ Use for all BirdNET system/integration tests to simulate `Recorder` `processed/` output |

---

## Phase 1: Architecture Spike — COMPLETED ✅

**Goal:** Time-boxed evaluation of inference methods to finalize the architectural approach.

### Tasks
- [x] Create a temporary script in `scripts/spikes/birdnet/` testing 10-second audio chunks, processing multiple chunks in succession.
- [x] Benchmark memory footprint AND initialization time of `birdnetlib` (community wrapper) vs. bare-metal `tflite_runtime.Interpreter`.
- [x] Optimize post-processing: use numpy boolean mask instead of Python for-loop over all 6,522 species scores (25× faster).
- [x] Document findings in [ADR-0027](../../adr/0027-birdnet-inference-engine.md) (Inference Engine).

#### Implementation Insights from Spike (for Phase 3)
- **Pre-compute `allowed_mask`** at init: `np.array([label in allowed_species for label in labels], dtype=bool)` — avoids 6,522-element Python loop per window
- **Numpy vectorized filtering**: `mask = (scores >= min_conf) & allowed_mask; hits = np.where(mask)[0]` — iterate only over actual detections (typically 3-6)
- **No resampling needed**: Recorder delivers 48 kHz S16LE WAVs; BirdNET model expects 48 kHz
- **Native CPU Threading**: A single thread (`num_threads=1`) is entirely sufficient for near real-time inference.
- **Sigmoid convention**: `1.0 / (1.0 + np.exp(sensitivity * clip(x, -15, 15)))` with `sensitivity = -1.0` (negative!)
- **Meta-model input**: `[latitude, longitude, week_48]` as float32, threshold ≥ 0.03 for location filtering

---

## Phase 2: Service Scaffold & Database Foundation (Commit 2)

**Goal:** Establish the `birdnet` service container, extend existing core schemas, and prepare DB + workspace.
**User Stories:** Preparation for US-B01, US-B03, US-B04.

### Tasks
- [x] Scaffold `services/birdnet/` (directories, `pyproject.toml`, `.env` mapping).
- [x] **Extend** existing `BirdnetSettings` in `packages/core/src/silvasonic/core/config_schemas.py` with new fields (`clip_padding_seconds: float = 3.0`, `overlap: float = 0.0`, `sensitivity: float = 1.0`, `threads: int = 1`, `processing_order: Literal["oldest_first", "newest_first"] = "oldest_first"`). Note: `enabled` is NOT added here — it lives in the `managed_services` table (ADR-0029).
- [x] **Create** generic DB-fallback and polling configuration via `BirdnetEnvSettings` (`SILVASONIC_POLLING_INTERVAL_S`, `SILVASONIC_DB_RETRY_INTERVAL_S`) according to the centralized worker resilience pattern (ADR-0030).
- [x] **Extend** existing `birdnet` section in `services/controller/config/defaults.yml` to match the updated schema.
- [x] **Add** `clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)` to the existing `Detection` model (`packages/core/src/silvasonic/core/database/models/detections.py`).
- [x] **Create** a new Pydantic schema `BirdnetDetectionDetails` in `packages/core/src/silvasonic/core/schemas/detections.py` to enforce the data contract for the JSONB `details` field (must include `model_version`, `sensitivity`, `overlap`, `confidence_threshold`, `location_filter_active`, `lat`, `lon`, `week`).
- [x] **Add** `birdnet` entry to `scripts/workspace_dirs.txt`.
- [x] Create `Containerfile` with standard `python:3.13-slim-bookworm` base image including `ai-edge-litert`, `numpy`, `soundfile` dependencies.
- [x] Initialize `SilvaService` base class. Read `system_config` on startup for `BirdnetSettings`, `SystemSettings` (latitude, longitude) — use `SystemConfig` model.

### Testing (Phase 2)
- [x] **`unit`** — `packages/core/tests/unit/test_service.py`: **Extend** existing `test_birdnet_settings_defaults`.
- [x] **`smoke`** — `tests/smoke/conftest.py` + `test_health.py`: Add `birdnet_container` fixture and `test_birdnet_healthy` smoke test.

---

## Phase 3: Inference Loop & Worker Pull Orchestration (Commit 3)

**Goal:** Implement the asynchronous analysis loop that pulls segments and generates detections.
**User Stories:** US-B01 (Automatic detection), US-B03 (Location logic), US-B04 (Confidence threshold).

### Tasks
- [x] Implement Worker Pull pattern (`SELECT ... FOR UPDATE SKIP LOCKED` on `recordings`). Respect dynamic `processing_order` setting for `ORDER BY time` ASC/DESC. Update `recordings.analysis_state` JSONB with `{"birdnet": "done"}` after processing.
- [x] Implement centralized Exception catching around the Worker Pull loop to sleep for `DB_RETRY_INTERVAL_S` on transient database issues (ADR-0030).
- [x] Implement the inference engine logic determined by the Phase 1 Spike.
- [x] Map DB runtime config (latitude, longitude from `SystemSettings`; `min_conf`, `sensitivity`, `overlap` from `BirdnetSettings`) to inference parameters. Derive `week` automatically.
- [x] Implement explicit memory management: e.g. `del audio_chunk` after inference, periodic `gc.collect()`.
- [x] Implement strictly standard multi-phase logging via `BirdnetStats` and `TwoPhaseWindow` class.
- [x] Save results using the existing `Detection` ORM model — set `worker='birdnet'`. Use the raw English string provided by the model for `label` and `common_name` temporarily. **Must populate `details` JSONB** with inference context (e.g., `model_version`, `sensitivity`, `overlap`, `confidence_threshold`, `location_filtered`).

### Testing (Phase 3)
- [x] **`unit`** — `services/birdnet/tests/unit/test_worker.py`: Test graceful shutdown logic (`shutdown_event.is_set()` between chunks stops processing).
- [x] **`integration`** — `services/birdnet/tests/integration/test_worker_pull.py`: Level 3. Using `testcontainers` and a synthetic recording, claim via `FOR UPDATE SKIP LOCKED`, mock the inference engine, and verify `detections` rows and `analysis_state` updates.
- [x] **`system`** — `tests/system/test_birdnet_real_inference.py`: Run real inference via the chosen Engine against the 10s preprocessed test WAV fixtures to ensure actual classifications work without mocking.

---

## Phase 4: Controller System Config Orchestration (Commit 4)

**Goal:** Provide execution capabilities in the Controller for the BirdNET worker based on the `managed_services` table (ADR-0029).
**Context:** The BirdNET service is now standalone viable. We must extend the Controller's `Reconciler` to start/stop this background worker. Lifecycle orchestration reads from `managed_services`, NOT from `system_config` JSONB.

### Tasks
- [ ] Create `worker_registry.py` with a robust statically typed array `SYSTEM_WORKERS` containing a `BackgroundWorker` dataclass configured for `"birdnet"` (incl. `mem_limit=512m`, `oom_score_adj=500`).
- [ ] Create `worker_evaluator.py` containing a generic `SystemWorkerEvaluator` that queries the `managed_services` table for `enabled = True` rows and matches them against the registry to build `Tier2ServiceSpec` objects.
- [ ] Refactor `_reconcile_once` in the `ReconciliationLoop` to securely invoke both `DeviceStateEvaluator` and `SystemWorkerEvaluator`. Isolate each with `try...except` blocks to prevent worker configuration mismatches from halting active `recorder` container execution.
- [ ] Implement `ManagedServiceSeeder`: On Controller startup, seed `managed_services` rows (`INSERT ON CONFLICT DO NOTHING`) for each worker in the registry (start: `birdnet`, `enabled=True`).

### Testing (Phase 4)
- [ ] **`unit`** — Add unit tests for `Reconciler._reconcile_once` to ensure it safely catches simulated exceptions from the worker evaluator while maintaining active hardware specs.
- [ ] **`integration`** — Add `tests/integration/test_system_worker_evaluator.py`: Instantiate `SystemWorkerEvaluator` against a real PostgreSQL testcontainer. Verify it correctly queries `managed_services` and maps enabled rows to `Tier2ServiceSpec`, excluding `enabled=False` workers (Rule: Mocking DB in integration tests is FORBIDDEN).
- [x] **`system`** — Add `tests/system/test_singleton_worker_lifecycle.py`: Validate full `ReconciliationLoop` state transitions. Ensure changing `enabled` in the DB reliably starts/stops the BirdNET worker via Podman without impacting the Recorder.
- [ ] **`system` (Regression)** — Audit existing system tests (`test_controller_lifecycle.py`, `test_crash_recovery.py`). Since BirdNET is `enabled=True` by default in `managed_services`, existing tests asserting `len(containers) == 1` will fail. You must disable background workers in the test seeder or update the container tracking assertions.

---

## Phase 5: Service Status & Lifecycle Integration (Commit 5)

**Goal:** Integrate BirdNET fully into the Silvasonic ecosystem (Controller, Heartbeats).
**User Stories:** US-B05 (Analysis status via Heartbeat), US-B06 (Enable/Disable via DB/Controller).

### Tasks
- [ ] `SilvaService` already provides Heartbeat functionality. Implement `get_extra_meta()` in the `BirdNETService` class to inject backlog numbers (remaining unanalyzed recordings) into the standard Redis heartbeat payload.
- [ ] Ensure lean graceful shutdown logic inside `run()` accurately breaks long-running tasks.

### Testing (Phase 5)
- [ ] **`unit`** — `services/birdnet/tests/unit/test_heartbeat.py`: Assert that `get_extra_meta()` returns valid backlog payloads.
- [ ] **`integration`** — `services/birdnet/tests/integration/test_backlog_metrics.py`: Verify the backlog counting query against a real Testcontainers database.
- [ ] **`system`** — `tests/system/test_birdnet_lifecycle.py`: Using real Podman with isolated network, test: Controller starts BirdNET container → Heartbeat in Redis → Controller stops BirdNET → Exits cleanly.
- [ ] **`smoke`** — `tests/smoke/test_health.py`: Extend with `test_birdnet_heartbeat_in_redis`.

---

## Phase 6: Audio Clip Extraction (Commit 6)

**Goal:** Extract and persist short audio clips for each detection.
**User Stories:** US-B01 (clip storage), US-B02 (playback preparation).

### Tasks
- [ ] Implement clip extraction using `soundfile`: read detection time range ± `clip_padding_seconds` (from `BirdnetSettings`) from the processed WAV file, write to `birdnet/clips/`.
- [ ] Clip naming convention: `{recording_id}_{start_ms}_{end_ms}_{label}.wav`. Store the relative path (`clips/...`) in `detections.clip_path`.
- [ ] Ensure `birdnet/clips/` directory is created at service startup.

### Testing (Phase 6)
- [ ] **`unit`** — `services/birdnet/tests/unit/test_clip_extraction.py`: Test clip filename generation, path construction, label sanitization, padding clamping.
- [ ] **`integration`** — `services/birdnet/tests/integration/test_clip_pipeline.py`: Run the full clip extraction pipeline using `testcontainers`.

---

## Phase 7: Final System Audit & Documentation (Commit 7)

**Goal:** Polish the system, verify system behavior, and finalize docs.
**User Stories:** Core backend implementations (US-B01, US-B03, US-B04, US-B07 logic) verified via DB-Viewer. UI-dependent stories (US-B02, US-B05, US-B06) deferred to v0.9.0 web interface.

### Tasks
- [ ] Verify `check-all` passes (lint, mypy, all tests up to smoke/system).
- [ ] Create `services/birdnet/README.md` using `services/_template_readme.md` boilerplate and convert `docs/services/birdnet.md` to a link-stub (per `STRUCTURE.md` §4).
- [ ] Update `docs/glossary.md` with new domain terms (Audio Clip, Analysis Backlog, Singleton/Background Worker).
- [ ] Update `docs/index.md` to reflect the newly integrated BirdNET service and documentation structure.
- [x] **Add** `"detections"` to `_CLEANUP_TABLES` in `tests/integration/conftest.py`. (Resolved dynamically via `clean_database`)

### Testing (Phase 7)
- [ ] **`system`** — `tests/system/test_birdnet_pipeline.py`: Full pipeline integration: Recorder → Indexer → BirdNET claims, analyzes, writes `detections` and extracts clips.
- [ ] **`system_hw_manual`** — `tests/system/test_hw_birdnet_pipeline.py`: End-to-end acoustics test. Human plays bird sound near active UltraMic → system captures, indexer triggers, BirdNET detects. Enable via `enabled=true` system config setting.

---

## Phase 8: Version Bump & Release v0.8.0 (Commit 8)

**Goal:** Formalize the release strictly according to `release_checklist.md`.

### Tasks
- [ ] **Release Decision:** Verify that the `managed_services` seed for `birdnet` has `enabled=True` by default (to fulfill US-B01: 'automatically analyzed' out of the box) before tagging.
- [ ] Ensure branch is clean and `just ci` finishes successfully.
- [ ] Update `__version__` in `packages/core/src/silvasonic/core/__init__.py`.
- [ ] Update version in the root `pyproject.toml`.
- [ ] Update version status in `ROADMAP.md` and the root `README.md`.
- [ ] Run `uv lock` to synchronize the lockfile.
- [ ] Create annotated Git tag `v0.8.0` (`git tag -a v0.8.0 -m "v0.8.0 — BirdNET"`) and push to upstream.

---

## Out of Scope (Deferred)

| Item                   | Target Version |
| ---------------------- | -------------- |
| Real Web-Interface UI  | v0.9.0         |
| Taxonomy Metadata Init (i18n) | v0.9.0 (Download [BirdNET-Pi l18n files](https://github.com/Nachtzuster/BirdNET-Pi/tree/main/model/l18n) as seeders. Note: CC BY-NC-SA 4.0 license!) |
| Push-based Orchestration| Rejected (ADR-0018) |
| Janitor: Clip cleanup  | Follow-up ([Issue](../issues/008-clip-cleanup-janitor.md)) |
