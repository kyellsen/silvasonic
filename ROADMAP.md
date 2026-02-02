# Silvasonic Implementation Roadmap

This roadmap tracks the implementation status of all services, organized by Architectural Tiers (as defined in `README.md`) and Dataflow dependency.

**Legend:**
- 🔴 **Missing/Template**: Service placeholder exists but is empty or offers only a template/skeleton.
- 🟡 **Partially Implemented**: Core features exist but are incomplete.
- 🟢 **Fully Implemented**: Feature-complete according to specification.
- ✅ **Verified**: Fully implemented (or stable partials) and verified by automated tests.

---

## 0. Shared Core
Foundation library used by all services.

| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **packages/core** | 🟡 ✅ | **High** (Integration) | Shared library. DB models & Migrations (TimescaleDB) and Redis client are implemented and **Verified** via integration tests. Shared business logic is missing. |

---

## 1. Tier 1: Infrastructure
Managed by Podman Compose. Provides the runtime environment and extensive system management.

| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **services/database** | 🟢 ✅ | **High** (Indirect) | PostgreSQL + TimescaleDB (Docker). functionality verified via `core` integration tests. |
| **services/redis** | 🟢 ✅ | **High** (Indirect) | Redis Cache/Queue (Docker). Connectivity verified via `core` integration tests. |
| **services/gateway** | 🟢 ✅ | **Manual** | Caddy Reverse Proxy. Configured directly in `podman-compose.yml` via Caddyfile. Considered done. |
| **services/controller** | 🟡 | **Unit** (Partial) | Hardware/Container manager & orchestrator. Core logic implemented, tests exist. |
| **services/monitor** | 🔴 | None | System Watchdog (CPU, Disk, Temp). |
| **services/web-interface** | 🔴 | None | **[Future Main UI]** Local management console (FastAPI + HTMX). Currently scaffolding. |
| **services/status-board** | 🟡 | **Unit** (Partial) | **[Interim Dev Tool]** Lightweight dashboard for backend verification & service monitoring. |
| **services/tailscale** | 🔴 | None | VPN mesh networking. |

---

## 2. Tier 2: Application
Managed by Controller. Implements the core bioacoustic pipeline (Dataflow logic).

| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **services/recorder** | 🟡 | **Unit** (Passing) | **[Input]** Capable of recording dual-stream (Raw/Processed) + Live Stream (MP3). Verified via unit tests. |
| **services/processor** | 🔴 | None | **[Process]** Indexes files, creates spectrograms, manages retention. |
| **services/batdetect** | 🔴 | None | **[Analyze]** On-device inference for bats. |
| **services/birdnet** | 🔴 | None | **[Analyze]** On-device inference for birds. |
| **services/weather** | 🔴 | None | **[Context]** Environmental sensor data collection. |
| **services/uploader** | 🔴 | None | **[Output]** Exfiltrates data to remote storage/API. |

---

## 3. Reference
| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **services/template** | 🔴 ✅ | **Low** (Smoke) | Reference implementation/Scaffolding. Contains basic smoke tests. |
