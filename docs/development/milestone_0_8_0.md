# Milestone v0.8.0 — Web-Interface (Dashboard & Service Control)

> **Target:** v0.8.0 — Real-time status dashboard, service control via DB + nudge
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0003](../adr/0003-web-architecture.md), [ADR-0017](../adr/0017-service-state-management.md), [ADR-0019](../adr/0019-unified-service-infrastructure.md), [ADR-0021](../adr/0021-frontend-stack.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [Web-Interface Stories](../user_stories/web_interface.md)

---

## Overview

The Web-Interface replaces the `web-mock` dev UI with a production-grade
dashboard built on FastAPI, Jinja2, htmx, Alpine.js, TailwindCSS/DaisyUI,
ECharts, and WaveSurfer.js (ADR-0003, ADR-0021).

### Key Capabilities

- Real-time service status via Redis Read+Subscribe pattern (ADR-0017)
- Service control: enable/disable services via `system_services` table + nudge
- Configuration editor for `system_config` values
- Recording browser with audio playback (WaveSurfer.js)
- Detection timeline with species visualizations (ECharts)

### Prerequisites

| Milestone  | Feature                                          |
| ---------- | ------------------------------------------------ |
| **v0.5.0** | Processor (Indexer + Janitor)                    |
| **v0.6.0** | Uploader (FLAC compression, remote sync)         |
| **v0.7.0** | Gateway (Caddy reverse proxy, HTTPS)             |

---

## Deferred Items from Earlier Milestones

### `system_services` Table Seeding & Reconciliation (from v0.5.0 Phase 5)

> **Context:** v0.5.0 originally planned seeding `processor` into the
> `system_services` table. This was deferred because:
>
> 1. The `system_services` table exists (DB schema + ORM model) but has
>    **zero consumers** — no service reads from or writes to it.
> 2. The Controller Reconciler derives desired state from `devices` +
>    `microphone_profiles` (for Recorders) and `compose.yml` dependencies
>    (for Tier 1 services like Processor).
> 3. Seeding rows without a consumer is dead code.
>
> **v0.8.0 is the right milestone** because the Web-Interface is the first
> consumer: it reads `system_services.enabled` to show toggle switches, and
> writes `enabled=false` + publishes a nudge to disable services (ADR-0017).
>
> See: [ADR-0017](../adr/0017-service-state-management.md) §2 "Desired State → Database"

#### Tasks

- [ ] Implement `SystemServiceSeeder` in Controller seeder:
  - Seed Tier 1 services: `controller`, `processor` (`enabled=true`, `status=active`)
  - Seed Tier 2 singletons when added: `birdnet` (v0.9.0), `weather` (v1.2.0)
  - Multi-instance Tier 2 (Recorder, Uploader) derive state from domain tables — NOT seeded here
- [ ] Extend Controller Reconciler to read `system_services.enabled` for Tier 1 services:
  - If `enabled=false` for Processor → Controller stops the Processor container
  - If `enabled=true` → Controller ensures it is running
- [ ] Web-Interface: render `system_services` rows as toggle switches in the admin panel
- [ ] Web-Interface: toggle writes `enabled` to DB + `PUBLISH silvasonic:nudge "reconcile"`

#### Tests

- [ ] Unit: `test_system_service_seeder` — seeds `controller` + `processor` rows
- [ ] Unit: `test_reconciler_reads_system_services` — `enabled=false` → stops container
- [ ] Integration: `test_controller_seeds_system_services` — fresh DB contains expected rows
- [ ] E2E: `test_toggle_service_via_ui` — Playwright: click toggle → service stops → heartbeat disappears

---

## Phase 1: Service Architecture

**Goal:** Create the `web` service following the Service Blueprint, replacing `web-mock`.

### Tasks

- [ ] Scaffold `services/web/` following the Service Blueprint
- [ ] Migrate relevant `web-mock` functionality
- [ ] FastAPI + Jinja2 + htmx + Alpine.js stack (ADR-0003)
- [ ] TailwindCSS v4 + DaisyUI v5 build pipeline (ADR-0021)
- [ ] SSE endpoint for real-time Redis status updates
- [ ] Compose integration with Gateway dependency

---

## Phase 2: Dashboard & Status

**Goal:** Real-time service status dashboard using Read+Subscribe pattern.

### Tasks

- [ ] Dashboard page: service cards with live health status (Redis heartbeats)
- [ ] System overview: disk usage, CPU, memory (from heartbeat `meta.resources`)
- [ ] Recording statistics: total indexed, pending analysis, storage used
- [ ] Service control toggles (requires `system_services` seeding above)

---

## Phase 3: Configuration & Settings

**Goal:** Operator-facing configuration editor for `system_config` values.

### Tasks

- [ ] Settings page: form-based editing of `system_config` JSONB values
- [ ] Validation against Pydantic schemas before DB write
- [ ] Nudge on save → Controller restarts affected service
- [ ] User management: password change, RBAC (admin/viewer)

---

## Phase 4: Recording Browser & Audio

**Goal:** Browse, filter, and playback recorded audio segments.

### Tasks

- [ ] Recording list with sort/filter (time, sensor, duration, status)
- [ ] Audio player using WaveSurfer.js v7 (ADR-0021)
- [ ] Spectrogram visualization
- [ ] Detection overlay on waveform (when BirdNET results available)

---

## Phase 5: Visualization & Charts

**Goal:** ECharts-based detection timeline and species statistics.

### Tasks

- [ ] Detection timeline: species activity over time
- [ ] Species frequency chart: top-N detected species
- [ ] Environmental correlation: detections vs. weather data (when available)

---

## Out of Scope (Deferred)

| Item                                     | Target Version |
| ---------------------------------------- | -------------- |
| Multi-station central dashboard          | post-v1.0.0    |
| Live Opus audio stream (Icecast embed)   | v1.1.0         |
| Mobile-optimized responsive layout       | post-v1.0.0    |
| Alert/notification system                | post-v1.0.0    |

> **Note:** The `web-mock` service remains available as a dev/debug tool
> alongside the production `web` service until v1.0.0 stabilization.
