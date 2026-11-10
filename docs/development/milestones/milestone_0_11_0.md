# Milestone v0.11.0 — Web-Interface (Svelte)

> **Target:** v0.11.0 — The station's interface: a Svelte single-page app on the Station API, replacing `web-mock`
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0036](../../adr/0036-svelte-spa-frontend.md), [ADR-0021](../../adr/0021-frontend-design-system.md), [ADR-0032](../../adr/0032-api-first-station-contract.md), [ADR-0017](../../adr/0017-service-state-management.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [Dashboard Stories](../../user_stories/dashboard.md), [Web-Interface Stories](../../user_stories/web_interface.md)

---

## Overview

This milestone takes over the scope the former v0.9.0 planned for a FastAPI + Jinja2 + htmx interface (ADR-0003). Under ADR-0036 the interface is a SvelteKit app in static mode: the Gateway serves its files, and it talks to the station only through `/api/v1`. There is no web container. The design system of ADR-0021 stays.

### Prerequisites

| Milestone   | Feature                               |
| ----------- | ------------------------------------- |
| **v0.10.0** | Station API with authentication and roles |

---

## Phase 1: Decisions

### Tasks

- [ ] Accept or reject ADR-0036; on acceptance set ADR-0003 to *Superseded* and update the documents ADR-0036 lists (`AGENTS.md` §5 Web row, ADR-0021, `docs/services/web_interface.md`)

---

## Phase 2: Application Skeleton

**Goal:** A built app the Gateway serves, with login and both languages.

### Tasks

- [ ] SvelteKit (Svelte 5, TypeScript, `adapter-static`), built at image build time
- [ ] Tailwind CSS + DaisyUI themes `silvadark` / `silvalight` (ADR-0021)
- [ ] Message catalogues for English and German; species names come from the API (AGENTS.md §2)
- [ ] Login and session handling against the API (ADR-0034)
- [ ] Gateway serves the build; Playwright end-to-end tests in CI

---

## Phase 3: Dashboard & Status

**Goal:** Live state of the station at a glance.

### Tasks

- [ ] Service cards with live health from the API (heartbeats)
- [ ] System overview: disk, CPU, memory, clock sync state
- [ ] Recording statistics: indexed, pending analysis, storage used
- [ ] Service control toggles (API, v0.10.0 Phase 4)

---

## Phase 4: Settings & Users

### Tasks

- [ ] Form-based editing of settings, validated by the API
- [ ] User management for administrators: invite, role, revoke (ADR-0034)

---

## Phase 5: Recordings & Audio

### Tasks

- [ ] Recording list with sort and filter (time, microphone, duration, state)
- [ ] Player with Wavesurfer.js v7; spectrogram drawn in the browser
- [ ] Detection overlay on the waveform

---

## Phase 6: Detections & Charts

### Tasks

- [ ] Detection timeline and top species (ECharts), from the rollups of v0.9.0
- [ ] Species pages with description and image (v0.9.0 Phase 5)

---

## Phase 7: Retire `web-mock`

### Tasks

- [ ] Remove `web-mock` from compose and the Gateway once the app covers its views (ADR-0036)

---

## Out of Scope (Deferred)

| Item                                    | Target Version |
| --------------------------------------- | -------------- |
| Access from outside the LAN             | v0.12.0        |
| Live audio stream (Icecast)             | v1.1.0         |
| Weather correlation charts              | v1.2.0         |
| Multi-station central dashboard         | post-v1.0.0    |
| Alert / notification system             | post-v1.0.0    |
