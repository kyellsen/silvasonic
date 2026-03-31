# Silvasonic

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

> **Status:** v0.5.2 — Core Infrastructure Upgrade ✅

---

## What is Silvasonic?

**AS-IS:** Silvasonic is a professional-grade, containerized recording system designed for long-term bioacoustic monitoring in the field. 

**TO-BE:** The goal for **v1.0.0** is to transform a Raspberry Pi 5 into a resilient recording station capable of capturing the entire soundscape — from avian vocalizations to ultrasonic bat calls.

**AS-IS:** **Target Audience:** Researchers, conservationists, and bioacoustic enthusiasts requiring robust, unsupervised data collection.

For the long-term vision and design philosophy see **[VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)**. For the milestone roadmap see **[ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)**.

---

## Quick Start

### Prerequisites

- Linux (e.g., Debian or Fedora)
- **Python 3.13** (required, `>=3.13, <3.14`)
- **uv** installed — Python package manager ([Installation](https://docs.astral.sh/uv/getting-started/installation/))
- **just** installed — command runner ([Installation](https://github.com/casey/just#installation))
- **Podman** & **podman-compose** installed

### Setup

```bash
git clone https://github.com/kyellsen/silvasonic.git
cd silvasonic
cp .env.example .env   # adjust settings as needed
just init               # uv sync, pre-commit hooks, workspace directories
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
├── pyproject.toml       # Workspace root, tooling config (Ruff, Mypy, Pytest)
├── compose.yml          # Container orchestration (Podman Compose)
├── justfile             # Developer commands (init, build, start, stop, check, test, …)
├── mkdocs.yml           # Documentation site configuration (MkDocs Material)
├── conftest.py          # Pytest root configuration
├── .env.example         # Environment template (copy to .env)
├── docs/                # Single Source of Truth — architecture, ADRs, specs
│   └── index.md         # Documentation entry point
├── packages/            # Shared Python packages (namespace: silvasonic.*)
│   ├── core/            # silvasonic-core: service base class, DB, Redis, heartbeat
│   └── test-utils/      # silvasonic-test-utils: shared testcontainer fixtures
├── services/            # Container service definitions & Containerfiles
│   ├── database/        # TimescaleDB / PostgreSQL
│   ├── controller/      # Hardware/Container manager
│   ├── recorder/        # Audio capture (FFmpeg, Dual Stream)
│   └── web-mock/        # Dev UI shell (FastAPI + Jinja2 + HTMX)
├── scripts/             # Build & lifecycle scripts (Python)
└── tests/               # Cross-cutting tests (integration, system, smoke, e2e)
```

---

## Current Services

**AS-IS:** The architecture is organized into **Tier 1** (Infrastructure, managed by Podman Compose) and **Tier 2** (Application, managed by Controller, **immutable**). Currently implemented:

| Service        | Tier | Role                                                                                     | Status     |
| -------------- | ---- | ---------------------------------------------------------------------------------------- | ---------- |
| **database**   | 1    | TimescaleDB / PostgreSQL — central state management                                      | ✅ Running  |
| **redis**      | 1    | Status bus — Pub/Sub heartbeats, Key-Value status cache (ephemeral)                      | ✅ Running  |
| **controller** | 1    | Hardware/Container manager — health monitoring, placeholder orchestration                | ✅ Partial  |
| **web-mock**   | 1    | Dev UI shell — FastAPI + Jinja2, hardcoded mock data (precursor to v0.9.0 Web-Interface) | ✅ Running  |
| **recorder**   | 2    | Audio Capture — FFmpeg engine, dual-stream WAV output (ADR-0024)                          | ✅ Partial  |

> For the full target architecture (13 services across two tiers) see **[VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)**. For version milestones see **[ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)**.

---

## Developer Commands

All commands are run via **[just](https://github.com/casey/just)**. Use `just --list` for a full overview.

### Container Lifecycle

| Command         | Description                                      |
| --------------- | ------------------------------------------------ |
| `just init`     | Initialize project (uv sync, hooks, workspace)   |
| `just build`    | Build all container images                        |
| `just start`    | Start all services                                |
| `just stop`     | Stop all services                                 |
| `just restart`  | Stop + start                                      |
| `just logs`     | Show aggregated service logs                      |
| `just status`   | Show service status                               |
| `just reset`    | Factory reset (clean → init → build → start)     |

### Code Quality & Testing

| Command           | Description                                                    |
| ----------------- | -------------------------------------------------------------- |
| `just fix`        | Auto-fix (Ruff format + lint fixes)                            |
| `just lint`       | Ruff lint (read-only)                                          |
| `just check`      | Quick quality gate: Lock → Ruff → Mypy → Unit tests           |
| `just check-all`  | Full CI pipeline: Lint → Type → Unit → Int → Build → System → Smoke → E2E |
| `just test`       | Dev tests (Unit + Integration)                                 |
| `just test-unit`  | Unit tests only                                                |
| `just test-int`   | Integration tests (Testcontainers)                             |
| `just test-system`| System lifecycle tests (Podman + built images)                 |
| `just test-smoke` | Smoke tests                                                    |
| `just test-hw`    | Hardware tests (real USB microphone required)                  |
| `just test-e2e`   | End-to-end Playwright tests                                    |
| `just test-all`   | All tests except hardware                                      |

### Maintenance & Docs

| Command        | Description                                    |
| -------------- | ---------------------------------------------- |
| `just clear`   | Clean root directory + caches                  |
| `just clean`   | clear + delete container volumes               |
| `just nuke`    | clean + delete .venv + images (full reset)     |
| `just prune`   | Remove dangling container images               |
| `just docs`    | Start MkDocs live server (localhost:8085)       |
| `just docs-build` | Build static documentation site             |

---

## Testing

**AS-IS:** Silvasonic uses a structured test pyramid with explicit markers. Every test must carry one of:

| Marker        | Scope                              | Command            |
| ------------- | ---------------------------------- | ------------------- |
| `unit`        | Fast, isolated, mocked             | `just test-unit`    |
| `integration` | External services (Testcontainers) | `just test-int`     |
| `system`      | Full Podman lifecycle              | `just test-system`  |
| `system_hw`   | Real USB hardware required         | `just test-hw`      |
| `smoke`       | Quick health checks on images      | `just test-smoke`   |
| `e2e`         | Browser tests (Playwright)         | `just test-e2e`     |

Service-specific tests live inside `services/<svc>/tests/`. Cross-cutting tests in `tests/`.

---

## Key Documentation

| Document                           | Audience    | Purpose                                                           |
| ---------------------------------- | ----------- | ----------------------------------------------------------------- |
| **[README.md](https://github.com/kyellsen/silvasonic/blob/main/README.md)**         | 👤 Humans    | Project overview, quick start, structure                          |
| **[VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)**         | 👤 + 🤖       | Vision, services architecture, design philosophy                  |
| **[ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)**       | 👤 + 🤖       | Milestone roadmap (version targets & status)                      |
| **[AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)**         | 🤖 AI Agents | Binding rules, constraints & conventions for AI coding assistants |
| **[docs/index.md](https://github.com/kyellsen/silvasonic/blob/main/docs/index.md)** | 👤 + 🤖       | Full technical documentation (architecture, 24 ADRs, specs)       |

> **📚 Local Docs:** Run `just docs` to start the MkDocs live server at `http://localhost:8085`.

> **🤖 AI Agents:** Your instructions are in **[AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)**. Read it first before doing any work on this repository.

---

## Contact

- 🌐 Website: [silvasonic.de](https://silvasonic.de/)
- 📧 E-Mail: [io@silvasonic.de](mailto:io@silvasonic.de)

---

## Licence

Available under the [Apache 2.0 License](https://github.com/kyellsen/silvasonic/blob/main/LICENCE).
