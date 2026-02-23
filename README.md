# Silvasonic

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

> **Status:** v0.1.0 — Requirements Engineering & Specification

---

## What is Silvasonic?

**AS-IS:** Silvasonic is a professional-grade, containerized recording system designed for long-term bioacoustic monitoring in the field. 

**TO-BE:** The goal for **v1.0.0** is to transform a Raspberry Pi 5 into a resilient recording station capable of capturing the entire soundscape — from avian vocalizations to ultrasonic bat calls.

**AS-IS:** **Target Audience:** Researchers, conservationists, and bioacoustic enthusiasts requiring robust, unsupervised data collection.

For the long-term vision and design philosophy see **[VISION.md](VISION.md)**. For the milestone roadmap see **[ROADMAP.md](ROADMAP.md)**.

---

## Quick Start

### Prerequisites

- Linux (e.g., Debian or Fedora)
- **uv** installed
- **just** installed — command runner ([Installation](https://github.com/casey/just#installation))
- **Podman** & **podman-compose** installed

### Setup

```bash
git clone https://github.com/kyellsen/silvasonic.git
cd silvasonic
cp .env.example .env   # adjust settings as needed
just init               # create workspace directories & pull images
just build              # build all container images
just start              # start all services
```

---

## Project Structure

```
silvasonic/
├── AGENTS.md            # AI agent rules (binding for all AI tools)
├── VISION.md            # Long-term vision & architecture
├── ROADMAP.md           # Milestone roadmap (version targets & status)
├── compose.yml          # Container orchestration
├── justfile             # Developer commands (init, build, start, stop, clean, nuke)
├── docs/                # Single Source of Truth — architecture, ADRs, specs
│   └── index.md         # Documentation entry point
├── packages/            # Shared Python packages (namespace: silvasonic.*)
├── services/            # Container service definitions & Containerfiles
├── scripts/             # Build & lifecycle scripts
└── tests/               # Cross-cutting tests
```

---

## Current Services

**AS-IS:** The architecture is organized into **Tier 1** (Infrastructure, managed by Podman Compose) and **Tier 2** (Application, managed by Controller, **immutable**). Currently implemented:

| Service        | Tier | Role                                                                                     | Status     |
| -------------- | ---- | ---------------------------------------------------------------------------------------- | ---------- |
| **database**   | 1    | TimescaleDB / PostgreSQL — central state management                                      | ✅ Running  |
| **redis**      | 1    | Status bus — Pub/Sub heartbeats, Key-Value status cache (ephemeral)                      | ✅ Running  |
| **controller** | 1    | Hardware/Container manager — health monitoring, placeholder orchestration                | ✅ Partial  |
| **web-mock**   | 1    | Dev UI shell — FastAPI + Jinja2, hardcoded mock data (precursor to v0.8.0 Web-Interface) | ✅ Running  |
| **recorder**   | 2    | Audio Capture — health monitoring, placeholder recording loop                            | ✅ Scaffold |

> For the full target architecture (13 services across two tiers) see **[VISION.md](VISION.md)**. For version milestones see **[ROADMAP.md](ROADMAP.md)**.

---

## Key Documentation

| Document                           | Audience    | Purpose                                                           |
| ---------------------------------- | ----------- | ----------------------------------------------------------------- |
| **[README.md](README.md)**         | 👤 Humans    | Project overview, quick start, structure                          |
| **[VISION.md](VISION.md)**         | 👤 + 🤖       | Vision, services architecture, design philosophy                  |
| **[ROADMAP.md](ROADMAP.md)**       | 👤 + 🤖       | Milestone roadmap (version targets & status)                      |
| **[AGENTS.md](AGENTS.md)**         | 🤖 AI Agents | Binding rules, constraints & conventions for AI coding assistants |
| **[docs/index.md](docs/index.md)** | 👤 + 🤖       | Full technical documentation (architecture, ADRs, specs)          |

> **🤖 AI Agents:** Your instructions are in **[AGENTS.md](AGENTS.md)**. Read it first before doing any work on this repository.

---

## Contact

- 🌐 Website: [silvasonic.de](https://silvasonic.de/)
- 📧 E-Mail: [io@silvasonic.de](mailto:io@silvasonic.de)

---

## Licence

See [LICENCE](LICENCE).
