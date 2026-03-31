# Milestone v0.1.0 — Requirements Engineering & Specification

> **Target:** v0.1.0 — Requirements Engineering & Specification
>
> **Status:** ✅ Done
>
> **References:** [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md), [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md), [docs/index.md](../index.md)
>
> **User Stories:** n/a (specification milestone — no runtime features)

---

## Phase 1: Repository & Tooling

**Goal:** Establish the repository structure, build tooling, and developer workflow.

### Tasks

- [x] Initialize Git repository with `.gitignore`, `LICENSE`, and root docs
- [x] Set up `uv` as Python package manager (ADR-0001)
- [x] Set up `just` as command runner with `justfile` recipes (`init`, `build`, `start`, `stop`, `clean`, `nuke`)
- [x] Configure `ruff` (linting + formatting) and `mypy` (type checking)
- [x] Configure `pre-commit` hooks
- [x] Create `.env.example` with all project environment variables
- [x] Set up `pyproject.toml` for root and service packages (ADR-0002)

---

## Phase 2: Architecture & ADRs

**Goal:** Document all architectural decisions as Architecture Decision Records.

### Tasks

- [x] Create ADR template (`docs/adr/_template.md`)
- [x] Write ADRs 0001–0023 covering:
  - Package management (0001, 0002)
  - Frontend architecture (0003, 0021)
  - Container runtime & rootless compliance (0004, 0007)
  - Code separation & domain isolation (0005, 0008)
  - Storage & data sharing (0006, 0009, 0015)
  - Naming conventions (0010)
  - Audio recording strategy (0011)
  - Validation (0012)
  - Container management & deployment (0013, 0014)
  - Microphone profiles (0016)
  - Service state & messaging (0017, 0018, 0019)
  - Resource limits & QoS (0020)
  - Live log streaming (0022)
  - Configuration management (0023)

> **Note:** ADRs created during later milestones (e.g., ADR-0024: FFmpeg Audio Engine, written during v0.4.0) are not listed here. See the [ADR index](../adr/README.md) for the complete list.

---

## Phase 3: Core Package & Database

**Goal:** Implement the shared `silvasonic.core` namespace package and database schema.

### Tasks

- [x] Create `packages/core/` with `silvasonic.core` namespace
- [x] Implement database schema (`silvasonic.core.models`):
  - `devices`, `microphone_profiles`, `system_config`, `system_services`, `users` tables
- [x] Implement Pydantic schemas (`silvasonic.core.schemas`)
- [x] Implement shared settings module (`silvasonic.core.settings`)
- [x] Implement health server (`silvasonic.core.health`)
- [x] Set up TimescaleDB / PostgreSQL container in `compose.yml`

---

## Phase 4: Service Specifications & User Stories

**Goal:** Specify all planned services and capture user requirements.

### Tasks

- [x] Write planned service specifications in `docs/services/`:
  - Controller, Recorder, Processor, Uploader, BirdNET, BatDetect, Weather, Icecast, Gateway
- [x] Write user stories for Controller (`docs/user_stories/controller.md`): US-C01–C09
- [x] Write user stories for Recorder (`docs/user_stories/recorder.md`): US-R01–R07
- [x] Create user story template (`docs/user_stories/_template.md`)
- [x] Create domain glossary (`docs/glossary.md`)
- [x] Create architecture specs in `docs/arch/`:
  - Filesystem governance, messaging patterns, microphone profiles

---

## Phase 5: CI Pipeline & QA

**Goal:** Establish the testing framework and continuous quality assurance.

### Tasks

- [x] Set up `pytest` with marker-based test organization (`unit`, `integration`, `e2e`, `smoke`)
- [x] Create test directory structure: `tests/unit/`, `tests/integration/`, `tests/smoke/`
- [x] Implement `justfile` recipes for test execution (`just test`, `just check-all`)
- [x] Set up Podman Compose for integration testing
- [x] Write initial smoke tests for container health

---

## Out of Scope (Deferred)

| Item                                      | Target Version |
| ----------------------------------------- | -------------- |
| Redis status bus                          | v0.2.0         |
| `SilvaService` base class                 | v0.2.0         |
| Tier 2 container management               | v0.3.0         |
| Audio recording                           | v0.4.0         |
| Web-Interface (production)                | v0.8.0         |

> **Note:** This milestone is purely specification and scaffolding — no runtime service functionality is implemented.
