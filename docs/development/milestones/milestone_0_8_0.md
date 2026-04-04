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
- Runs BirdNET analytical model
- Writes detections (`detections` table) and correlates with taxonomy.

### Prerequisites

| Milestone  | Feature                                          |
| ---------- | ------------------------------------------------ |
| **v0.5.0** | Processor (Indexer + Janitor)                    |

---

## Phase 1: Service Scaffold & Database Foundation (Commit 1)

**Goal:** Establish the `birdnet` service container, its basic configuration, and DB schemas.
**User Stories:** Preparation for US-B01, US-B03, US-B04.

### Tasks
- [ ] Scaffold `services/birdnet/` (directories, `pyproject.toml`, `.env` mapping).
- [ ] Create `Containerfile` including TensorFlow Lite (`tflite-runtime`), `soundfile`, `numpy`.
- [ ] Initialize `SilvaService` base class and basic DB models for `recordings` (read) and `detections` (write).
- [ ] Read `system_config` on startup for Latitude, Longitude, und Confidence-Threshold.
- [ ] **Testing (`unit` & `smoke`):** Add `tests/unit/test_config.py` for config parsing. Add smoke tests (`just test-smoke`) to ensure the container builds and starts gracefully.

---

## Phase 2: Inference Loop & Worker Pull Orchestration (Commit 2)

**Goal:** Implement the asynchronous analysis loop that pulls segments and generates detections.
**User Stories:** US-B01 (Automatic detection), US-B03 (Location logic), US-B04 (Confidence threshold).

### Tasks
- [ ] Implement Worker Pull pattern (`SELECT ... FOR UPDATE SKIP LOCKED` auf `recordings`).
- [ ] Integrate BirdNET-Analyzer (`birdnetlib` API oder CLI Subprocess) für `data/processed` Audio-Segmente.
- [ ] Mappe DB-Laufzeitkonfigurationen (Latitude, Longitude, `min_conf`) dynamisch auf die Analyzer-Eingabeparameter.
- [ ] Parse den rohen Analyzer-Output (z.B. temporäre CSV-Dateien) und addiere die lokalen Clip-Zeitstempel auf den echten Aufnahme-Zeitstempel.
- [ ] Save Ergebnisse in die `detections` DB table, mappe auf Taxonomie und lösche temporäre Output-Dateien des Analyzers.
- [ ] **Testing (`unit` & `integration`):** Mock inference in unit tests. Write `tests/integration/test_worker_pull.py` using `testcontainers` (PostgreSQL) to verify atomic DB locking and `detections` insertion.

---

## Phase 3: Service Status & Lifecycle Integration (Commit 3)

**Goal:** Integrate BirdNET fully into the Silvasonic ecosystem (Controller, Heartbeats).
**User Stories:** US-B05 (Analysis status via Heartbeat), US-B06 (Enable/Disable via DB/Controller).

### Tasks
- [ ] Implement Heartbeat publisher pushing current state ("active", "waiting", backlogs) to Redis.
- [ ] Update Controller's Seeder to include `birdnet` in `system_services` (enabled by default).
- [ ] Ensure clean graceful shutdown logic in BirdNET to safely abort/finish active inferences on `SIGTERM`.
- [ ] Add basic routes to `services/web-mock` to verify detection data (US-B02 preparation).
- [ ] **Testing (`system`):** Add `tests/system/test_birdnet_lifecycle.py` to test start/stop via Controller and verify Redis heartbeat presence. 

---

## Phase 4: Final System Audit & Documentation (Commit 4)

**Goal:** Polish the system, ensure robust E2E behavior, and clean up docs.
**User Stories:** All US-Bxx verified.

### Tasks
- [ ] Verify `check-all` passes (lint, mypy, all tests up to smoke/system).
- [ ] Move `docs/services/birdnet.md` to `services/birdnet/README.md` and convert the doc file to a link-stub.
- [ ] **Testing (`system` & `e2e`):** Run full system pipeline tests ensuring the Recorder-Processor-BirdNET pipeline does not clash and respects `oom_score_adj=+500`.

---

## Phase 5: Version Bump & Release v0.8.0 (Commit 5)

**Goal:** Formalize the release according to `release_checklist.md`.

### Tasks
- [ ] Ensure branch is clean and `just check-all` finishes successfully.
- [ ] Update `pyproject.toml` files to version `0.8.0` (core + services).
- [ ] Run `just lock` to synchronize lockfiles.
- [ ] Update `ROADMAP.md` (set v0.8.0 to ✅ Done, v0.9.0 to Current).
- [ ] Create signed Git tag `v0.8.0` and push to upstream.

---

## Out of Scope (Deferred)

| Item                   | Target Version |
| ---------------------- | -------------- |
| Real Web-Interface UI  | v0.9.0         |
| Push-based Orchestration| Rejected (ADR-0018) |
