# Milestone v0.13.0 — Supervisor & Quadlets

> **Target:** v0.13.0 — systemd supervises every service; recording starts and keeps running without the Controller and the database
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0014](../../adr/0014-dual-deployment-strategy.md), [ADR-0013](../../adr/0013-tier2-container-management.md), [ADR-0029](../../adr/0029-system-worker-orchestration.md), [ADR-0007](../../adr/0007-rootless-os-compliance.md), [ADR-0020](../../adr/0020-resource-limits-qos.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** `n/a`

---

## Overview

Today the Controller starts Recorders and workers through the Podman socket, from a privileged container. If the Controller or the database is down, no new Recorder starts. ADR-0014 already moves stations from compose to Quadlets; this milestone goes one step further and lets systemd supervise the Tier 2 containers too, as template units (`silvasonic-recorder@<microphone>`). The Controller keeps detection, profile matching, enrollment and seeding, and writes the configuration the units read. It loses the Podman client, the container specification and the log forwarder.

The privilege gain only holds if the Controller does not start units itself: a Controller with access to the systemd user bus could start any unit as the user, as much as with the Podman socket today. ADR-0042 therefore puts the start in udev or a small host component.

### Prerequisites

| Milestone   | Feature                                                   |
| ----------- | --------------------------------------------------------- |
| **v0.8.1**  | Hardware measurement (decides the resource budget)        |
| **v0.10.0** | Status without Redis (ADR-0041), if accepted              |

---

## Phase 1: Decisions

### Tasks

- [ ] Spike on the reference hardware: one Recorder as a template unit, started by udev on hot-plug
- [ ] ADR-0042: systemd as supervisor. Who starts a unit (udev or a host component, never the Controller), what the Controller writes, `WatchdogSec` / `sd_notify` instead of heartbeat eviction, journald as log source; on acceptance it amends ADR-0013, ADR-0029 and ADR-0007
- [x] Stations run on Podman Quadlets, development stays on compose (ADR-0014)

---

## Phase 2: Tier 1 as Quadlets

**Goal:** Every Tier 1 service is a systemd unit on a station.

### Tasks

- [ ] Quadlet unit files for every Tier 1 service, with the resource limits and OOM order of ADR-0020 (`OOMScoreAdjust=` / `PodmanArgs=`, replacing the compose run argument)
- [ ] Boot order and restart policy in the units instead of compose dependencies

---

## Phase 3: Tier 2 as Template Units

**Goal:** A Recorder starts when its microphone appears, even with the Controller stopped.

### Tasks

- [ ] Template units for the Recorder and each analysis worker
- [ ] The Controller writes per-microphone configuration; the unit reads it at start
- [ ] `WatchdogSec` with `sd_notify` from the services replaces the Controller's heartbeat eviction
- [ ] Logs come from journald; the log forwarder is removed
- [ ] The Controller container no longer mounts the Podman socket and is no longer privileged

---

## Phase 4: Tests & CI

**Goal:** The supervision path is tested where it runs.

### Tasks

- [ ] A test harness for systemd user units (container with systemd or a VM) for system tests
- [ ] System tests for hot-plug, crash recovery and the watchdog run against units instead of the Podman API
- [ ] Development keeps compose; one code path for the services, two ways to start them

---

## Out of Scope (Deferred)

| Item                                   | Target Version |
| -------------------------------------- | -------------- |
| Installation and updates on a station  | v0.14.0        |
| Services in a venv instead of a container (left open by ADR-0042) | post-v1.0.0 |
