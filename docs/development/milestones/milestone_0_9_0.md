# Milestone v0.9.0 — Station Data Foundation

> **Target:** v0.9.0 — The schema and database engine the station keeps from v1.0.0 on, and versioned migrations from this release on
>
> **Status:** ⏳ Planned (naming done, SQLite implemented on a branch)
>
> **References:** [ADR-0033](../../adr/0033-unified-naming-and-global-identifiers.md), [ADR-0037](../../adr/0037-sqlite-station-database.md), [ADR-0018](../../adr/0018-worker-pull-orchestration.md), [ADR-0030](../../adr/0030-database-resilience.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** `n/a` (foundation for [API](../../user_stories/api.md) and [Dashboard](../../user_stories/dashboard.md))

---

## Overview

Everything after this release builds on the station's data: the API (v0.10.0), the interface (v0.11.0) and the update mechanism (v0.14.0). This milestone changes the schema for the last time by editing the init script: names and identifiers per ADR-0033, the engine per ADR-0037. From v0.9.0 on, every schema change ships as a versioned migration, because a station in the field cannot be recreated.

A station on v0.8.1 recreates its database once when it updates to v0.9.0. The recordings on disk are kept and indexed again; detections and upload history are lost.

### Prerequisites

| Milestone  | Feature                    |
| ---------- | -------------------------- |
| **v0.8.1** | Field Hardening (released) |

---

## Phase 1: Decisions

**Goal:** Every ADR this milestone implements is accepted before its code lands.

### Tasks

- [x] ADR-0033 (naming and global identifiers) accepted
- [x] Accept or reject ADR-0037 (SQLite); on acceptance set ADR-0026 to *Superseded* and carry out the document changes ADR-0037 lists
- [ ] ADR-0039: the migration tool (required by ADR-0033 before v1.0.0); it must rebuild tables, as SQLite's `ALTER TABLE` cannot change types or constraints (ADR-0037)
- [ ] Reference hardware for v1.0.0 decided (Raspberry Pi 4 or 5, RAM), based on the v0.8.1 measurement
- [ ] ADR-0040: storage classes and the hardware floor, superseding ADR-0015 (SD card allowed for 48 kHz stations, SSD required for ultrasonic recording)

---

## Phase 2: One Name per Concept (ADR-0033)

**Goal:** A field means the same in the database, the models, the API and the interface.

### Tasks

- [x] Schema, ORM models, services, microphone profiles and tests renamed; UUIDv7 identifiers
- [x] System tests pass after the rename
- [ ] Settings schema evolution: how a new or renamed field in `settings` reaches an existing station (covered by the migration ADR)

---

## Phase 3: SQLite Station Database (ADR-0037)

**Goal:** One database file in WAL mode instead of a database server.

### Tasks

- [x] `silvasonic.core.database` opens every connection with WAL, `synchronous=NORMAL`, foreign keys and a busy timeout; `STRICT` tables
- [x] BirdNET claims a recording in a short transaction with a lease instead of a row lock held during inference
- [ ] Hourly rollups per microphone and species, written with each detection
- [ ] Janitor: batched retention of old detections, regular WAL checkpoint
- [x] Remove the `database` container, its port and the `POSTGRES_*` variables
- [x] Integration tests run against a temporary database file instead of a TimescaleDB container

---

## Phase 4: Versioned Migrations

**Goal:** A station can be updated without losing data from here on.

### Tasks

- [ ] Migration tool integrated per its ADR
- [ ] Baseline migration equals the v0.9.0 schema; the init script is retired or generated from it
- [ ] A test that upgrades a database at the baseline to the current head

---

## Phase 5: Species Reference Data

**Goal:** Detected species carry a description and image for the interface.

### Tasks

- [ ] Wikipedia enrichment into the `species` row (implemented, not yet committed)
- [ ] Run enrichment as its own background task instead of inside the analysis loop, so a station without internet never waits on it
- [ ] Store author and licence of each image before the interface shows it

---

## Phase 6: Release

### Tasks

- [ ] `just ci` passes, including smoke and system tests
- [ ] Repeat the v0.8.1 measurement on the same hardware with the same script: SQLite against PostgreSQL, RAM per container, fsync load on the SD card
- [ ] Release Checklist (Feature Release)
- [ ] Station: recreate the database once (last time), rebuild images

---

## Out of Scope (Deferred)

| Item                                         | Target Version |
| -------------------------------------------- | -------------- |
| Station API on the new schema                | v0.10.0        |
| Fleet server database (TimescaleDB fits there) | post-v1.0.0    |
