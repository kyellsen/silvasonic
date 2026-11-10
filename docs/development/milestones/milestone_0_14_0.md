# Milestone v0.14.0 — Rollout & Updates

> **Target:** v0.14.0 — A station is installed from scratch and updates itself in place, with a way back
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0014](../../adr/0014-dual-deployment-strategy.md), [ADR-0033](../../adr/0033-unified-naming-and-global-identifiers.md), [ADR-0037](../../adr/0037-sqlite-station-database.md), [Deployment](../../deployment/README.md), [Release Checklist](../release_checklist.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** `n/a`

---

## Overview

Today a station is updated by `git pull`, `just build` and `just start` on the device, and the images are built there. That is fine for development and not for a station in the field. This milestone takes over the deployment phase the former v1.0.0 plan held, and adds what a safe update needs: versioned images from CI, a backup before the update, the migrations of v0.9.0, and a rollback. The station pulls its update; nobody needs to reach it.

For v1.0.0 the update works at application level: images, database and configuration. A read-only operating system image with A/B slots is the step before the first fleet rollout; whether it belongs in v1.0.0 already is Kyell's decision (Phase 1).

### Prerequisites

| Milestone   | Feature                                        |
| ----------- | ---------------------------------------------- |
| **v0.9.0**  | Versioned migrations                           |
| **v0.12.0** | Remote access (to watch and repair an update)  |
| **v0.13.0** | Services as systemd units                      |

---

## Phase 1: Decisions

### Tasks

- [ ] ADR-0043: rollout and updates. It states at least:
  - The station pulls updates; an operator does not push them
  - Where images come from and how a release is selected
  - What a rollback restores, and what happens to a database already migrated
  - What the operating system may update unattended: nothing that restarts Podman, systemd or the kernel or triggers a reboot, because that interrupts recording
  - All station state lives under one data root, and the installer is idempotent and also runs at image build time, so an A/B image fits underneath later without migration
  - The A/B operating system image as the step before the first fleet rollout, with the price of deferring it: stations installed earlier must be reflashed
- [ ] Decide whether the A/B operating system image belongs in v1.0.0

---

## Phase 2: Versioned Images

**Goal:** A station runs exactly the images CI built and tested for a release.

### Tasks

- [ ] CI builds every image for `arm64` and publishes it with the release version
- [ ] Release tags drive image publishing (Release Checklist)
- [ ] Recorder and worker images are referenced by version, not `latest`
- [ ] Every image installs from the lockfile (`uv sync --frozen`); the BirdNET image still installs with `uv pip install -e`, past the lockfile

---

## Phase 3: Installation

**Goal:** A fresh device becomes a running station without manual steps beyond the documented ones.

### Tasks

- [ ] Idempotent installer: Podman, linger, data root, units, configuration, Gateway login, Tailscale join
- [ ] Per-station configuration (name, coordinates) separated from shared defaults (carried over from the former v1.0.0 Phase 2)
- [ ] `docs/deployment/` describes installation, replacing its placeholder

---

## Phase 4: Update & Rollback

**Goal:** An update either completes or leaves the station on its previous version, still recording.

### Tasks

- [ ] Backup before every update (`VACUUM INTO`, ADR-0037)
- [ ] Update: fetch images → migrate the database → restart services → health check
- [ ] Rollback on a failed health check: previous images, database from the backup
- [ ] The Recorder is restarted last and only once its new image is present (Data Capture Integrity)
- [ ] Unattended operating system updates configured within the limits of ADR-0043
- [ ] Test of the full lifecycle on the reference hardware: install → configure → update → rollback

---

## Out of Scope (Deferred)

| Item                                     | Target Version |
| ---------------------------------------- | -------------- |
| Read-only A/B operating system image     | before the first fleet rollout (Phase 1 decides) |
| Fleet-wide rollout of many stations      | post-v1.0.0    |
| Updates over metered uplinks             | v1.5.0         |
