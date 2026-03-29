# Silvasonic — Vision

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

---

## Core Philosophy: Data Capture Integrity

**TO-BE:** Silvasonic is a **recording station first**. Every design decision is subordinate to one principle:

> **Data Capture Integrity is paramount.**  
> Any operation that risks the continuity of sound recording is forbidden.

**TO-BE:** The system is designed to run autonomously for **years** without human intervention, buffering data locally on high-speed NVMe storage and synchronizing with central servers (e.g., Nextcloud) via a **Store & Forward** architecture.

---

## Architecture Vision

### Hardware Platform
- **Raspberry Pi 5** as the compute node
- **NVMe SSD** for high-throughput, reliable local storage
- Professional-grade audio interface for full-spectrum capture

### Soundscape Scope
**TO-BE:** Silvasonic captures the **entire soundscape** — from low-frequency avian vocalizations to ultrasonic bat echolocation calls. The system is not limited to a single species or frequency band.

### Containerized
**AS-IS:** All services run in **Podman containers** (see ADR-0004). Processes run as root inside the container for simplicity; Podman's rootless mode maps container-root to an unprivileged host user automatically. This maximizes security and isolation while simplifying deployment and updates on remote devices.

### Store & Forward
**TO-BE:** Recordings are written to local NVMe storage first. Synchronization to central infrastructure happens opportunistically — the station never depends on network connectivity for its primary mission.

---

## Services Architecture

**TO-BE:** The system is composed of containerized services organized into two tiers.

### Tier 1: Infrastructure (Dev: Podman Compose · Prod: Quadlets)

| Service           | Role                                                                                                                                                       | Criticality             | Status       |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------ |
| **database**      | Central state management (TimescaleDB / PostgreSQL)                                                                                                        | Critical                | ✅ AS-IS      |
| **redis**         | Status bus (Pub/Sub heartbeats, Key-Value status cache) and Reconcile-Nudge for immediate Controller wake-up (ADR-0017, ADR-0019)                          | Life Support            | ✅ AS-IS      |
| **controller**    | Hardware/Container manager. Detects USB microphones, manages service lifecycles via State Reconciliation (DB + Redis nudge). No HTTP API beyond `/healthy` | Critical                | ✅ AS-IS      |
| **web-interface** | Local management console. In production: full management console. Dev predecessor: `web-mock` (v0.2.0)                                                    | Life Support / Optional | ✅ AS-IS ¹    |
| **gateway**       | Caddy Reverse Proxy handling HTTPS and authentication                                                                                                      | Critical                | ⏳ TO-BE v0.7 |
| **processor**     | Data Ingestion, Indexing, and Janitor. Immutable — config at startup, restart to reconfigure. Clean-up logic is critical for survival                      | Critical                | ✅ AS-IS      |
| **icecast**       | Streaming server. Receives live Opus audio from Recorder instances and serves it via HTTP to Web-Interface and clients                                     | Life Support / Optional | ⏳ TO-BE v1.1 |
| **tailscale**     | Provides secure, zero-config remote access and VPN mesh networking                                                                                         | Life Support / Optional | ⏳ TO-BE v1.5 |

> ¹ Currently implemented as `web-mock` — a lightweight dev UI shell with mock data. Will be replaced by the full `web-interface` at v0.8.0.

### Tier 2: Application (Managed by Controller)

> **ALL TIER 2 CONTAINERS ARE IMMUTABLE!** The Processor (Tier 1) is also immutable — see [ADR-0019](docs/adr/0019-unified-service-infrastructure.md).

| Service       | Role                                                                                                                                                                                                                                                    | Criticality      | Status        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------- |
| **recorder**  | Critical path. Managed directly by Controller via Profile Injection (No DB Access). Captures audio via FFmpeg subprocess (ADR-0024), writes dual-stream output (Raw Native & Processed 48kHz) to NVMe. 🔮 Will send a live Opus stream to Icecast (v1.1.0) | Critical         | ✅ AS-IS       |
| **uploader**  | Handles data exfiltration. Compresses raw data (Native FLAC) and syncs to remote storage                                                                                                                                                                 | Critical         | ⏳ TO-BE v0.6  |
| **birdnet**   | On-device inference for avian species classification                                                                                                                                                                                                     | Core Feature     | ⏳ TO-BE v0.9  |
| **batdetect** | On-device inference for bat species classification                                                                                                                                                                                                       | Optional Feature | ⏳ TO-BE v1.3  |
| **weather**   | Correlates acoustic data with environmental measurements                                                                                                                                                                                                 | Optional Feature | ⏳ TO-BE v1.2  |

---

## Design Principles

1. **Resilience over Features** — The station must survive power outages, network loss, and disk pressure gracefully. Recording never stops unless physically impossible.
2. **Autonomy** — Zero human intervention required for normal operation. Self-healing, self-monitoring, self-reporting.
3. **Reproducibility** — Fully containerized builds with pinned versions. A fresh deployment must produce identical behavior.
4. **Transparency** — Structured logging (JSON), health metrics, and remote observability built in from day one.
5. **Security by Default** — Container isolation, minimal attack surface.
6. **Resource Isolation** — Every managed container runs with explicit memory and CPU limits (cgroups v2). The Recorder is protected from the OOM Killer via `oom_score_adj=-999`. Analysis workers are expendable; the recording stream is not. See [ADR-0020](docs/adr/0020-resource-limits-qos.md).

---

## Deployment & Fleet Management

**TO-BE:** Silvasonic supports two deployment models:

1. **Single Node:** Manual provisioning via local installer scripts.
2. **Fleet Mode:** "Zero-Touch" provisioning using a bootstrap image. The device connects to a VPN management network upon boot and pulls its configuration via **Ansible**.

---

## Roadmap

For the milestone roadmap see **[ROADMAP.md](ROADMAP.md)**.

---

## See Also

- **[README.md](README.md)** — Project overview, quick start, structure (human-facing)
- **[ROADMAP.md](ROADMAP.md)** — Milestone roadmap (version targets & status)
- **[AGENTS.md](AGENTS.md)** — Binding rules for AI coding assistants
- **[docs/index.md](docs/index.md)** — Full technical documentation

> **🤖 AI Agents:** This document is normative. When designing or implementing new services, you **MUST** consult the Services Architecture and Design Principles above. Do not build entire services autonomously — proceed step by step after human review.
