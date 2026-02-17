# Silvasonic

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

> **Status:** v0.1.0 (Initial Development / MVP)

---

## What is Silvasonic?

Silvasonic is a professional-grade, containerized recording system designed for long-term bioacoustic monitoring in the field. The goal for **v1.0.0** is to transform a Raspberry Pi 5 into a resilient recording station capable of capturing the entire soundscape — from avian vocalizations to ultrasonic bat calls.

**Target Audience:** Researchers, conservationists, and bioacoustic enthusiasts requiring robust, unsupervised data collection.

For the long-term vision, design philosophy, and roadmap see **[VISION.md](VISION.md)**.

---

## Quick Start

### Prerequisites

- Linux (e.g., Debian or Fedora)
- **uv** installed
- **Podman** & **podman-compose** installed — or Docker & docker-compose (not tested!)

### Setup

```bash
git clone https://github.com/kyellsen/silvasonic.git
cd silvasonic
cp .env.example .env   # adjust settings as needed
make init               # create workspace directories & pull images
make build              # build all container images
make start              # start all services
```

---

## Project Structure

```
silvasonic/
├── AGENTS.md            # AI agent rules (binding for all AI tools)
├── VISION.md            # Long-term vision & roadmap
├── compose.yml          # Container orchestration
├── Makefile             # Developer commands (init, build, start, stop, clean, nuke)
├── docs/                # Single Source of Truth — architecture, ADRs, specs
│   └── index.md         # Documentation entry point
├── packages/            # Shared Python packages (namespace: silvasonic.*)
├── services/            # Container service definitions & Dockerfiles
├── scripts/             # Build & lifecycle scripts
└── tests/               # Cross-cutting tests
```

---

## Current Services

The architecture is organized into **Tier 1** (Infrastructure, managed by Podman Compose) and **Tier 2** (Application, managed by Controller, **immutable**). Currently implemented:

| Service        | Tier | Role                                                                      | Status     |
| -------------- | ---- | ------------------------------------------------------------------------- | ---------- |
| **database**   | 1    | TimescaleDB / PostgreSQL — central state management                       | ✅ Running  |
| **controller** | 1    | Hardware/Container manager — health monitoring, placeholder orchestration | ✅ Scaffold |
| **recorder**   | 2    | Audio Capture — health monitoring, placeholder recording loop             | ✅ Scaffold |

> For the full target architecture (13 services across two tiers) see **[VISION.md](VISION.md)**.

---

## Key Documentation

| Document                           | Audience    | Purpose                                                           |
| ---------------------------------- | ----------- | ----------------------------------------------------------------- |
| **[README.md](README.md)**         | 👤 Humans    | Project overview, quick start, structure                          |
| **[VISION.md](VISION.md)**         | 👤 + 🤖       | Vision, services architecture, design philosophy, roadmap         |
| **[AGENTS.md](AGENTS.md)**         | 🤖 AI Agents | Binding rules, constraints & conventions for AI coding assistants |
| **[docs/index.md](docs/index.md)** | 👤 + 🤖       | Full technical documentation (architecture, ADRs, specs)          |

> **🤖 AI Agents:** Your instructions are in **[AGENTS.md](AGENTS.md)**. Read it first before doing any work on this repository.

---

## Licence

See [LICENCE](LICENCE).
