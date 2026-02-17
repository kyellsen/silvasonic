# Silvasonic — Vision

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

> **Status:** v0.1.0 (Initial Development / MVP)

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

### Containerized & Rootless
All services run in **rootless containers** (Podman/Docker). This maximizes security and isolation while simplifying deployment and updates on remote devices.

### Store & Forward
Recordings are written to local NVMe storage first. Synchronization to central infrastructure happens opportunistically — the station never depends on network connectivity for its primary mission.

---

## Design Principles

1. **Resilience over Features** — The station must survive power outages, network loss, and disk pressure gracefully. Recording never stops unless physically impossible.
2. **Autonomy** — Zero human intervention required for normal operation. Self-healing, self-monitoring, self-reporting.
3. **Reproducibility** — Fully containerized builds with pinned versions. A fresh deployment must produce identical behavior.
4. **Transparency** — Structured logging (JSON), health metrics, and remote observability built in from day one.
5. **Security by Default** — Rootless containers, minimal attack surface.

---

## Roadmap

| Version    | Milestone                                         | Status        |
| ---------- | ------------------------------------------------- | ------------- |
| **v0.1.0** | MVP — Recording, local storage, basic lifecycle   | 🔨 In Progress |
| v0.2.0     | Store & Forward sync to Nextcloud/S3              | ⏳ Planned     |
| v0.3.0     | Processor service (BirdNET analysis, Janitor)     | ⏳ Planned     |
| v0.4.0     | Uploader service (FLAC conversion, cloud sync)    | ⏳ Planned     |
| v0.5.0     | On-device species detection (BirdNET integration) | ⏳ Planned     |
| v0.6.0     | Redis cache layer for inter-service messaging     | ⏳ Planned     |
| v1.0.0     | Production-ready field deployment                 | ⏳ Planned     |

---

## See Also

- **[README.md](README.md)** — Project overview, quick start, structure
- **[AGENTS.md](AGENTS.md)** — Binding rules for AI coding assistants
- **[docs/index.md](docs/index.md)** — Full technical documentation
