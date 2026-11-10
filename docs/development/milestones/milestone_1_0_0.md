# Milestone v1.0.0 — MVP

> **Target:** v1.0.0 — A complete station that runs locally and autonomously, is reachable on site and through Tailscale, and is updated safely
>
> **Status:** ⏳ Planned
>
> **References:** [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md), [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md), [Release Checklist](../release_checklist.md)
>
> **User Stories:** `n/a` (cross-cutting stabilization)

---

## Overview

v1.0.0 is the functional MVP: a station on the reference hardware chosen in v0.9.0 that records, analyses and shows its data without a cloud, runs unattended for months, is operated through its interface on site or remotely through Tailscale, and is updated with a way back. Every feature it needs lands in v0.9.0 to v0.14.0; this milestone adds no feature. It proves the station on real hardware and documents it.

### Prerequisites (must be completed first)

| Milestone   | Feature                                            |
| ----------- | -------------------------------------------------- |
| **v0.9.0**  | Station Data Foundation (schema, SQLite, migrations) |
| **v0.10.0** | Station API with authentication and roles          |
| **v0.11.0** | Web-Interface (Svelte)                             |
| **v0.12.0** | Secure Access (HTTPS, Tailscale)                   |
| **v0.13.0** | Supervisor & Quadlets                              |
| **v0.14.0** | Rollout & Updates                                  |

---

## Phase 1: Hardening & Reliability

**Goal:** The station survives extended unattended operation.

### Tasks

- [ ] Watchdog for all Tier 1 services (not just the Recorder)
- [ ] Log rotation for every container
- [ ] Storage health monitoring per storage class (ADR-0040): SMART for SSD, wear and error counters for SD cards where available
- [ ] Power-loss recovery: unclean shutdown → clean restart, no corrupt database or segment
- [ ] 72-hour soak test for memory leaks
- [ ] Every service recovers from a database lock timeout (ADR-0030), and from a Redis outage if ADR-0041 keeps Redis
- [ ] Dead-letter queue for failed uploads
- [ ] Measure the OOM order on the Pi: the Recorder is the last container killed (ADR-0020 §2.3)

---

## Phase 2: Security & Licensing Review

**Goal:** What v0.8.1, v0.10.0, v0.12.0 and v0.13.0 built holds up under review, and a station may be given or sold with what it ships.

### Tasks

- [ ] Review all environment variables for secrets exposure
- [ ] Scan container images for known vulnerabilities (Trivy or Grype) in CI
- [ ] Review the Recorder's device access (ADR-0007) against fewer rights; no change that risks recording. The Controller is no longer privileged after v0.13.0
- [ ] Review Redis access, if ADR-0041 keeps Redis
- [ ] Decide on the BirdNET model licence (CC BY-NC-SA 4.0) for stations that are sold: licence, alternative model, or user-installed model. Decided before Phase 3, because a different model changes what the trial validates
- [ ] Image licences of the species enrichment (Wikipedia, CC BY-SA): attribution shown wherever an image is shown
- [ ] Licences of the shipped binaries, FFmpeg builds included

---

## Phase 3: Field Trial

**Goal:** The release candidate runs on the reference hardware (decided in v0.9.0, [hardware](../../hardware.md)) under real conditions.

### Tasks

- [ ] Install a station from scratch with the v0.14.0 procedure
- [ ] At least two weeks of unattended operation with the supported microphones, including one update and one rollback
- [ ] `just test-hw-all` passes on the trial hardware

---

## Phase 4: Documentation & Release

**Goal:** Complete documentation for operators and contributors.

### Tasks

- [ ] Operator guide: installation, configuration, remote access, updates, monitoring, troubleshooting
- [ ] Contributor guide: development setup, testing, code style
- [ ] All service READMEs at `Status: implemented`
- [ ] All ADRs reflect the implementation; no ADR left *Proposed*
- [ ] Release Checklist (Feature Release), GitHub release with changelog

---

## Out of Scope (Deferred)

| Item                                   | Target Version |
| -------------------------------------- | -------------- |
| Icecast live streaming                 | v1.1.0         |
| Weather service                        | v1.2.0         |
| BatDetect inference                    | v1.3.0         |
| Metadata export                        | v1.4.0         |
| Metered uplinks (ADR-0038)             | v1.5.0         |
| Fleet server, multi-station dashboard  | post-v1.0.0    |

> **Note:** The former Phase 2, "Configuration Architecture Review", is resolved: `config/` sits at the repository root. Per-station configuration moved to v0.13.0 and settings schema evolution to v0.9.0. Quadlets and supervision moved to v0.13.0, installation and updates to v0.14.0; forced password change and roles to v0.10.0; HTTPS to v0.12.0.
