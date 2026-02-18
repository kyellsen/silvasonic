# Silvasonic — Vision

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

> **Status:** v0.1.0 — Foundation

---

## Core Philosophy: Data Capture Integrity

Silvasonic is a **recording station first**. Every design decision is subordinate to one principle:

> **Data Capture Integrity is paramount.**  
> Any operation that risks the continuity of sound recording is forbidden.

The system is designed to run autonomously for **years** without human intervention, buffering data locally on high-speed NVMe storage and synchronizing with central servers (e.g., Nextcloud) via a **Store & Forward** architecture.

---

## Architecture Vision

### Hardware Platform
- **Raspberry Pi 5** as the compute node
- **NVMe SSD** for high-throughput, reliable local storage
- Professional-grade audio interface for full-spectrum capture

### Soundscape Scope
Silvasonic captures the **entire soundscape** — from low-frequency avian vocalizations to ultrasonic bat echolocation calls. The system is not limited to a single species or frequency band.

### Containerized
All services run in **Podman containers** (see ADR-0004). Processes run as root inside the container for simplicity; Podman's rootless mode maps container-root to an unprivileged host user automatically. This maximizes security and isolation while simplifying deployment and updates on remote devices.

### Store & Forward
Recordings are written to local NVMe storage first. Synchronization to central infrastructure happens opportunistically — the station never depends on network connectivity for its primary mission.

---

## Services Architecture

The system is composed of containerized services organized into two tiers.

### Tier 1: Infrastructure (Dev: Podman Compose · Prod: Quadlets)

| Service        | Role                                                                                                                   | Criticality             |
| -------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| **database**   | Central state management (TimescaleDB / PostgreSQL)                                                                    | Critical                |
| **redis**      | Message broker for real-time heartbeats, pub/sub events, and service control                                           | Critical                |
| **gateway**    | Caddy Reverse Proxy handling HTTPS and authentication                                                                  | Critical                |
| **controller** | Hardware/Container manager. Dynamically detects USB microphones and manages service lifecycles                         | Critical                |
| **processor**  | Data Ingestion, Indexing, and Janitor. Clean-up logic is critical for survival                                         | Critical                |
| **icecast**    | Streaming server. Receives live Opus audio from Recorder instances and serves it via HTTP to Web-Interface and clients | Life Support / Optional |

| **web-interface** | Local management console. During development: lightweight status-board dashboard. In production: full management console | Life Support / Optional |
| **tailscale**     | Provides secure, zero-config remote access and VPN mesh networking                                                       | Life Support / Optional |

### Tier 2: Application (Managed by Controller)

> **ALL TIER 2 CONTAINERS ARE IMMUTABLE!**

| Service       | Role                                                                                                                                                                                                                | Criticality      |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| **recorder**  | Critical path. Managed directly by Controller via Profile Injection (No DB Access). Buffers audio in RAM, writes dual-stream output (Raw Native & Processed 48kHz) to NVMe, and sends a live Opus stream to Icecast | Critical         |
| **uploader**  | Handles data exfiltration. Compresses raw data (Native FLAC) and syncs to remote storage                                                                                                                            | Critical         |
| **birdnet**   | On-device inference for avian species classification                                                                                                                                                                | Optional Feature |
| **batdetect** | On-device inference for bat species classification                                                                                                                                                                  | Optional Feature |
| **weather**   | Correlates acoustic data with environmental measurements                                                                                                                                                            | Optional Feature |

---

## Design Principles

1. **Resilience over Features** — The station must survive power outages, network loss, and disk pressure gracefully. Recording never stops unless physically impossible.
2. **Autonomy** — Zero human intervention required for normal operation. Self-healing, self-monitoring, self-reporting.
3. **Reproducibility** — Fully containerized builds with pinned versions. A fresh deployment must produce identical behavior.
4. **Transparency** — Structured logging (JSON), health metrics, and remote observability built in from day one.
5. **Security by Default** — Container isolation, minimal attack surface.

---

## Deployment & Fleet Management

Silvasonic supports two deployment models:

1. **Single Node:** Manual provisioning via local installer scripts.
2. **Fleet Mode:** "Zero-Touch" provisioning using a bootstrap image. The device connects to a VPN management network upon boot and pulls its configuration via **Ansible**.

---

## Roadmap

| Version    | Milestone                                                                                                                   | Status    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------- | --------- |
| **v0.1.0** | Foundation — Repo structure, core pkg, DB, Controller & Recorder (placeholder), test suite, CI pipeline, docs, ADRs, Podman | ✅ Current |
| v0.2.0     | Controller manages Recorder lifecycle (start/stop)                                                                          | ⏳ Planned |
| v0.2.5     | Recorder writes .wav files, HotPlug USB mic support                                                                         | ⏳ Planned |
| v0.3.0     | Processor service (Ingestion, Indexing, Janitor)                                                                            | ⏳ Planned |
| v0.4.0     | Uploader (immutable Tier 2, Controller-managed)                                                                             | ⏳ Planned |
| v0.5.0     | Gateway (Caddy reverse proxy, HTTPS)                                                                                        | ⏳ Planned |
| v0.6.0     | Redis, Web-Interface — Real-time status dashboard, service control via Redis Pub/Sub                                        | ⏳ Planned |
| v0.7.0     | Web-Interface improvements — Extended management console, alerting                                                          | ⏳ Planned |
| v0.9.0     | Icecast — Live Opus audio stream from Recorder to Web-Interface                                                             | ⏳ Planned |
| v1.0.0     | MVP — Production-ready field deployment (Podman Quadlets, Ansible)                                                          | ⏳ Planned |
| v1.1.0     | BirdNET — On-device avian species classification                                                                            | ⏳ Planned |
| v1.2.0     | Weather — Environmental data correlation                                                                                    | ⏳ Planned |
| v1.3.0     | BatDetect — On-device bat species classification                                                                            | ⏳ Planned |
| v1.5.0     | Tailscale — Secure remote access, VPN mesh networking                                                                       | ⏳ Planned |

---

## See Also

- **[README.md](README.md)** — Project overview, quick start, structure (human-facing)
- **[AGENTS.md](AGENTS.md)** — Binding rules for AI coding assistants
- **[docs/index.md](docs/index.md)** — Full technical documentation

> **🤖 AI Agents:** This document is normative. When designing or implementing new services, you **MUST** consult the Services Architecture and Design Principles above. Do not build entire services autonomously — proceed step by step after human review.
