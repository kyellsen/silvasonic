# Silvasonic

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

> **Status:** v0.1.0 (Initial Development / MVP)

---

## What is Silvasonic?

Silvasonic is a professional-grade, containerized recording system designed for long-term bioacoustic monitoring in the field. It transforms a Raspberry Pi 5 into a resilient recording station capable of capturing the entire soundscape — from avian vocalizations to ultrasonic bat calls.

**Target Audience:** Researchers, conservationists, and bioacoustic enthusiasts requiring robust, unsupervised data collection.

For the long-term vision, design philosophy, and roadmap see **[VISION.md](VISION.md)**.

---

## Quick Start

### Prerequisites

- Raspberry Pi 5 with NVMe storage
- Container engine: **Podman** (default) or Docker — configured via `.env`
- Python ≥ 3.13, managed with **uv**

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

## Key Documentation

| Document                           | Audience    | Purpose                                                           |
| ---------------------------------- | ----------- | ----------------------------------------------------------------- |
| **[README.md](README.md)**         | 👤 Humans    | Project overview, quick start, structure                          |
| **[VISION.md](VISION.md)**         | 👤 Humans    | Long-term vision, design philosophy, roadmap                      |
| **[AGENTS.md](AGENTS.md)**         | 🤖 AI Agents | Binding rules, constraints & conventions for AI coding assistants |
| **[docs/index.md](docs/index.md)** | 👤 + 🤖       | Full technical documentation (architecture, ADRs, specs)          |

> **🤖 AI Agents:** Your instructions are in **[AGENTS.md](AGENTS.md)**. Read it first before doing any work on this repository.

---

## Licence

See [LICENCE](LICENCE).
