# Silvasonic — Roadmap

> **Status:** v0.8.0 — BirdNET ✅ · in progress: v0.8.1 — Field Hardening

---

## Milestone Roadmap

| Version    | Milestone                                                                                                                                                                                                                                                                 | Status        |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| **v0.1.0** | Requirements Engineering & Specification — Complete specification of all features, tech stack, architecture, and service logic up to v1.0.0 (MVP) in `.md` files with clear roadmap. Repo structure, core pkg, DB, CI pipeline, ADRs, Podman as implementation foundation | ✅ Done        |
| **v0.2.0** | Service Infrastructure — Redis container, `SilvaService` base class, `core.service`, `core.redis`, `core.heartbeat`. All services inherit unified lifecycle. Heartbeats go live (ADR-0019). Web-Mock dev UI                                                               | ✅ Done        |
| **v0.3.0** | Tier 2 Container Management — Podman lifecycle, USB Detection, Profile Matching & Auto-Enrollment, Config Seeding, Log Streaming (ADR-0022), Reconciliation Loop                                                                                                              | ✅ Done        |
| **v0.4.0** | Robust Audio Engine — FFmpeg Dual Stream (Raw `data/raw` + Processed `data/processed` 48kHz S16LE), Segment Promotion, Graceful Shutdown, Watchdog & Auto-Recovery                                                                                                            | ✅ Done        |
| **v0.5.0** | Analysis & Backend Orchestration — Processor Service (Indexer + Janitor), Recording Registration, Data Retention Policy, Config Seeding                                                                                                                                   | ✅ Done        |
| **v0.5.1** | Architecture & Stability Fixes — Core Data Integrity, USB Debouncing, Workspace mapping                                                                                                                                                                                   | ✅ Done        |
| **v0.5.2** | Core Infrastructure Upgrade — Python 3.13 adoption and runtime typing simplification                                                                                                                                                                                  | ✅ Done        |
| **v0.5.3** | Cloud Sync Preparatory Refactoring — Uploader wipe, storage_remotes DB drop, Test Suite Fixes                                                                                                                                                                           | ✅ Done        |
| **v0.6.0** | Processor Cloud Sync — Single-target Upload Worker (FLAC compression, rclone/rsync). Internal async worker within Processor (KISS, single-target)                                                                                                        | ✅ Done     |
| **v0.7.0** | Gateway (Caddy reverse proxy, HTTPS termination, internal routing)                                                                                                                                                                                                        | ✅ Done        |
| **v0.7.1** | DB-Viewer — Database inspector, Data Export UI & Custom SQL Execution                                                                                                                                                                                                     | ✅ Done        |
| **v0.8.0** | BirdNET — On-device avian species classification (Worker Pull via DB, ADR-0018)                                                                                                                                                                                           | ✅ Current     |
| v0.8.1     | Field Hardening (patch) — analysis gaps closed, true segment start times, clock-sync marker, flat Indexer cost, heartbeat grace period, OOM order under rootless Podman, internal ports off the network, per-installation Gateway login                                   | 🔨 In Progress |
| v0.9.0     | Station Data Foundation — one name per concept and global identifiers (ADR-0033), SQLite station database (ADR-0037), versioned schema migrations from this release on                                                                                                     | ⏳ Planned     |
| v0.10.0    | Station API — one versioned HTTP API as the only way clients read or change a station (ADR-0032), sessions, tokens and roles (ADR-0034), service status and logs without Redis (ADR-0041)                                                                                 | ⏳ Planned     |
| v0.11.0    | Web-Interface — Svelte single-page app on the Station API (ADR-0036): dashboard, recordings, detections, settings, service control. Replaces `web-mock`                                                                                                                   | ⏳ Planned     |
| v0.12.0    | Secure Access — HTTPS on every hostname (ADR-0035), remote access via Tailscale                                                                                                                                                                                           | ⏳ Planned     |
| v0.13.0    | Supervisor & Quadlets — systemd runs every service: Quadlets for Tier 1, template units for Recorders and workers; recording starts without Controller and database (ADR-0042)                                                                                            | ⏳ Planned     |
| v0.14.0    | Rollout & Updates — versioned images built by CI, station installation, update pulled by the station with backup, migration and rollback (ADR-0043)                                                                                                                       | ⏳ Planned     |
| v1.0.0     | MVP — a complete station that runs locally and autonomously, reachable on site and via Tailscale: hardening, security and licensing review, field trial on the reference hardware, operator documentation                                                                 | ⏳ Planned     |
| v1.0.0+    |                                                                                                                                                                                                                                                                           |               |
| v1.1.0     | Icecast — Live Opus audio stream from Recorder to Web-Interface                                                                                                                                                                                                           | ⏳ Planned     |
| v1.2.0     | Weather — Environmental data correlation                                                                                                                                                                                                                                  | ⏳ Planned     |
| v1.3.0     | BatDetect — On-device bat species classification                                                                                                                                                                                                                          | ⏳ Planned     |
| v1.4.0     | Metadata Export — Daily Parquet snapshot of recordings, detections, weather to cloud (Cloud-Sync extension, analytics-optimized)                                                                                                                                             | ⏳ Planned     |
| v1.5.0     | Metered Uplinks — what a station uploads over LTE or satellite, by data tier and connection class (ADR-0038)                                                                                                                                                              | ⏳ Planned     |

> **Pending decisions:** v0.9.0 to v0.14.0 build on ADRs that are still *Proposed* (0032, 0034–0038) or not yet written (0039–0043). The first task of each milestone is to accept or reject its ADRs; a rejection re-plans the milestone, not the code. Measurements on real hardware in v0.8.1 and v0.9.0 feed the decisions of v0.13.0 and v0.14.0.
>
> **Moved:** Tailscale was planned for v1.5.0 and is now part of v0.12.0, because v1.0.0 is reachable remotely. The marketing website (formerly v0.10.0) is its own project, `kyellsen/silvasonic.de`, and no longer a station version.

---

## Detailed Implementation Plans

For concrete, phase-level implementation tasks see:

- **[Milestone v0.1.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_1_0.md)** — Phases & tasks for Requirements Engineering & Specification
- **[Milestone v0.2.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_2_0.md)** — Phases & tasks for Service Infrastructure
- **[Milestone v0.3.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_3_0.md)** — Phases & tasks for Tier 2 Container Management
- **[Milestone v0.4.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_4_0.md)** — Phases & tasks for Audio Recording (Dual Stream)
- **[Milestone v0.5.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_5_0.md)** — Phases & tasks for Analysis & Backend Orchestration
- **[Milestone v0.6.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_6_0.md)** — Phases & tasks for Processor Cloud Sync (Upload Worker)
- **[Milestone v0.7.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_7_0.md)** — Gateway (Caddy reverse proxy, HTTPS termination, internal routing)
- **[Milestone v0.7.1](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_7_1.md)** — DB-Viewer
- **[Milestone v0.8.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_8_0.md)** — BirdNET (On-device Avian Inference)
- **[Milestone v0.8.1](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_8_1.md)** — Field Hardening (patch release)
- **[Milestone v0.9.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_9_0.md)** — Station Data Foundation (naming, SQLite, migrations)
- **[Milestone v0.10.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_10_0.md)** — Station API (contract, authentication, roles)
- **[Milestone v0.11.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_11_0.md)** — Web-Interface (Svelte single-page app)
- **[Milestone v0.12.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_12_0.md)** — Secure Access (HTTPS, Tailscale)
- **[Milestone v0.13.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_13_0.md)** — Supervisor & Quadlets (systemd units)
- **[Milestone v0.14.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_0_14_0.md)** — Rollout & Updates
- **[Milestone v1.0.0](https://github.com/kyellsen/silvasonic/blob/main/docs/development/milestones/milestone_1_0_0.md)** — MVP (hardening, security and licensing review, field trial, operator docs)

---

## See Also

- **[VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)** — Core philosophy, architecture, design principles
- **[README.md](https://github.com/kyellsen/silvasonic/blob/main/README.md)** — Project overview, quick start
- **[docs/index.md](https://github.com/kyellsen/silvasonic/blob/main/docs/index.md)** — Full technical documentation
